"""
tm_execute.py – CommandExecuteHandler: orchestrates the hole creation loop.
"""
import adsk.core, adsk.fusion, traceback, os
import tm_helpers
import tm_state
import tm_config
from tm_helpers import calc_blind_hole_depth_mm
from tm_geometry import (
    findCoplanarFace,
    findProfileForCircle,
    findExtrudeDirectionFromSketch,
    findChamferEdge,
    getGripRidgeChamferEdges,
    addChamferToEdge,
    addAngleChamferToEdge,
    findDistanceThroughBody,
    addBottomRadiusToBlindHole,
    create_grip_ridge_sketch,
)


def sketch_plane_of(parentSketch):
    """The plane or face a sketch was drawn on, or a plain explanation of why not.

    Fusion refuses to hand over `referencePlane` when a sketch sits on a model face and
    that face no longer exists at the current timeline position, because a later feature
    consumed or reshaped it. Raw, that arrives as

        RuntimeError: 3 : referencePlane is a BRefFace -
        need to roll timeline back before sketch

    in the middle of a traceback, which names neither the sketch nor anything to do
    about it. Rolling the timeline back here is not the answer: features created while
    rolled back land before the ones that consumed the face, which can break them. So
    the cause is named and the caller skips that point.

    The caller reads every plane before it cuts anything, so by the time this fires the
    culprit can only be a feature that was already in the timeline -- which is what
    makes "roll the timeline back" sound advice. It was not, while the add-in's own
    first cut could consume the face midway through a run.
    """
    try:
        return parentSketch.referencePlane
    except RuntimeError as e:
        if 'BRefFace' not in str(e) and 'referencePlane' not in str(e):
            raise
        raise RuntimeError(
            f'the sketch "{parentSketch.name}" is on a model face that Fusion will not '
            'resolve from this timeline position, and the target body has no face left '
            'in that sketch\'s plane to use instead. Check you picked the body the '
            'sketch was drawn on, or put the sketch on a construction plane, which '
            'nothing can consume.') from e


def summarise_failures(failures):
    """Render [(point_number, reason)] as one line per distinct reason.

    A reason that belongs to the sketch rather than the point -- a face a later
    feature has changed, say -- fails every point selected in that sketch. Saying
    it once with the points listed beats repeating the paragraph N times. Reasons
    keep the order they first occurred in.
    """
    by_reason = {}
    for point_number, reason in failures:
        by_reason.setdefault(reason, []).append(point_number)

    lines = []
    for reason, points in by_reason.items():
        if len(points) == 1:
            label = f'Point {points[0]}'
        else:
            label = 'Points ' + ', '.join(str(p) for p in points)
        lines.append(f'{label}: {reason}')
    return '\n'.join(lines)


class CommandExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            bodySelect = inputs.itemById('bodySelect')
            pointSelect = inputs.itemById('pointSelect')
            insertSize = inputs.itemById('insertSize')
            addChamfer = inputs.itemById('addChamfer')
            addBottomRadius = inputs.itemById('addBottomRadius')
            exportDebugInput = inputs.itemById('exportDebug')
            shouldExport = exportDebugInput is not None and exportDebugInput.value

            # Apply the dialog's parameters before anything reads CONFIG, so the
            # values on screen are the ones this run uses. They are not written to
            # config.ini here: that is what the Save button is for, so a one-off
            # tweak stays a one-off.
            tm_state.CONFIG.update(tm_config.read_settings_inputs(inputs))

            targetBody = bodySelect.selection(0).entity
            selectedPoints = [pointSelect.selection(i).entity for i in range(pointSelect.selectionCount)]

            insertName = insertSize.selectedItem.name
            tm_config.save_last_selected_insert(insertName)

            isBlindHole = tm_config.read_hole_type(inputs)
            includeChamfer = addChamfer.value if addChamfer else tm_state.CONFIG.get('chamfer_enabled_default', True)
            bottomRadiusChecked = addBottomRadius.value if addBottomRadius else tm_state.CONFIG.get('bottom_radius_enabled_default', False)
            includeBottomRadius = bottomRadiusChecked and isBlindHole
            showMessage = tm_state.CONFIG.get('show_success_message', True)

            tm_config.save_checkbox_states(includeChamfer, bottomRadiusChecked, showMessage, isBlindHole)

            is_grip_ridge = insertName in tm_state.GRIP_RIDGE_INSERTS

            if is_grip_ridge:
                # The values on screen, which the Save button persists separately
                spec = tm_config.read_grip_inputs(inputs, insertName)
                (clearanceDia, gripDepthMm, gripChamferSize,
                 gripRidgeDia, gripArcDistance, gripCount) = spec
                holeDia = clearanceDia
            else:
                holeDia, insertLen, minWall = tm_state.INSERT_SPECS[insertName]

            diameter = holeDia / 10.0   # mm -> cm

            successCount = 0
            failedCount = 0
            failures = []   # (point_number, reason)

            component = targetBody.parentComponent
            design = component.parentDesign
            timeline = None
            startIndex = -1

            if design and hasattr(design, 'timeline'):
                timeline = design.timeline
                if timeline:
                    startIndex = timeline.markerPosition

            # --- Pass 1: every sketch, while the face is still there -------------
            # Fusion will not create a sketch on a model face that a feature has
            # since reshaped, and the first hole reshapes the face the user's own
            # sketch sits on. Acquiring the plane inside the cutting loop therefore
            # worked for the first point and failed for all the rest, and rolling
            # the timeline back could never fix it because the add-in consumed the
            # face again on its own first cut.
            #
            # Measuring here is a bonus: direction and through-depth come off the
            # pristine body instead of one already part-full of holes.
            prepared = []
            for point_idx, point in enumerate(selectedPoints):
                parentSketch = point.parentSketch
                center2d = point.geometry

                try:
                    face = sketch_plane_of(parentSketch)
                except RuntimeError as planeError:
                    # Fusion would not resolve the face the sketch was drawn on. It
                    # does not have to: a face of the body lying in the sketch's plane
                    # puts the temp sketch in the same place, and is read off the body
                    # as it is now rather than out of the sketch's history.
                    face = findCoplanarFace(targetBody, parentSketch, center2d)
                    if face is None:
                        failedCount += 1
                        failures.append((point_idx + 1, str(planeError)))
                        continue
                    tm_helpers.log(
                        f'Point {point_idx+1}: referencePlane refused, using the '
                        f'coplanar face of {targetBody.name} instead')

                # Clean sketch without auto-projected body edges
                tempSketch = component.sketches.addWithoutEdges(face)
                tempSketch.name = f"TM_{insertName}_P{point_idx+1}"

                # Project original point to maintain parametric association
                projectedEntities = tempSketch.project(point)
                projectedPoint = projectedEntities.item(0)

                circle = None
                if is_grip_ridge:
                    profile_or_collection = create_grip_ridge_sketch(
                        tempSketch, projectedPoint.geometry, clearanceDia,
                        grip_ridge_dia_mm=gripRidgeDia,
                        grip_arc_distance_mm=gripArcDistance,
                        grip_count=gripCount)
                    if profile_or_collection is None:
                        failedCount += 1
                        failures.append(
                            (point_idx + 1, 'Could not create grip-ridge profile.'))
                        tempSketch.deleteMe()
                        continue
                else:
                    radius = holeDia / 2.0 / 10.0   # mm -> cm

                    circle = tempSketch.sketchCurves.sketchCircles.addByCenterRadius(
                        projectedPoint.geometry, radius)
                    tempSketch.geometricConstraints.addCoincident(
                        circle.centerSketchPoint, projectedPoint)

                    profile_or_collection = findProfileForCircle(tempSketch, circle)
                    if profile_or_collection is None:
                        failedCount += 1
                        failures.append(
                            (point_idx + 1, 'Could not create bore profile.'))
                        tempSketch.deleteMe()
                        continue

                # Export debug JSON if enabled
                if shouldExport:
                    try:
                        from tm_debug_export import export_sketch_data
                        export_dir = os.path.join(
                            os.path.dirname(os.path.dirname(__file__)), 'debug_exports')
                        os.makedirs(export_dir, exist_ok=True)
                        target_circle = circle
                        if is_grip_ridge:
                            target_circle = None
                            for circle_candidate in tempSketch.sketchCurves.sketchCircles:
                                if circle_candidate.centerSketchPoint.geometry.distanceTo(projectedPoint.geometry) < 1e-6:
                                    target_circle = circle_candidate
                                    break
                            if target_circle is None:
                                tm_helpers.log(f'Grip-ridge debug export skipped: central circle not found for point {point_idx+1}')

                        if target_circle is not None:
                            export_sketch_data(
                                tempSketch, target_circle, export_dir,
                                description=f"Point {point_idx+1} - {insertName}"
                            )
                    except Exception as e:
                        tm_helpers.log(f'Debug export failed for point {point_idx+1}: {e}')

                direction = findExtrudeDirectionFromSketch(parentSketch, center2d, targetBody)

                if direction is None:
                    failedCount += 1
                    failures.append((
                        point_idx + 1,
                        'Could not determine extrusion direction. Ensure the sketch '
                        'is on a planar face of the target body.'))
                    tempSketch.deleteMe()
                    continue

                if isBlindHole:
                    if is_grip_ridge:
                        depth_mm = gripDepthMm
                    else:
                        # Standard: insert length + extra depth + chamfer
                        chamfer = tm_state.CONFIG['chamfer_size'] if includeChamfer else 0.0
                        depth_mm = calc_blind_hole_depth_mm(
                            insertLen, tm_state.CONFIG['blind_hole_extra_depth'], chamfer)
                    depth_cm = depth_mm / 10.0   # mm -> cm
                else:
                    depth_cm = findDistanceThroughBody(
                        parentSketch, center2d, targetBody, direction)

                prepared.append({
                    'point_no': point_idx + 1,
                    'center2d': center2d,
                    'parentSketch': parentSketch,
                    'tempSketch': tempSketch,
                    'projectedPoint': projectedPoint,
                    'profile': profile_or_collection,
                    'direction': direction,
                    'depth_cm': depth_cm,
                })

            # --- Pass 2: cut, then chamfer and fillet ----------------------------
            extrudes = component.features.extrudeFeatures

            for item in prepared:
                extInput = extrudes.createInput(
                    item['profile'], adsk.fusion.FeatureOperations.CutFeatureOperation)
                dist = adsk.core.ValueInput.createByReal(item['depth_cm'])
                extent = adsk.fusion.DistanceExtentDefinition.create(dist)
                extInput.setOneSideExtent(extent, item['direction'])
                extInput.participantBodies = [targetBody]
                extrude = extrudes.add(extInput)

                if includeChamfer:
                    if is_grip_ridge:
                        # Grip-ridge: chamfer grip ridge arcs with the insert-specific chamfer size.
                        grip_chamfer_angle = tm_state.CONFIG.get('grip_chamfer_angle', 78)
                        gripEdges = getGripRidgeChamferEdges(
                            extrude, targetBody, item['tempSketch'],
                            item['projectedPoint'].geometry,
                            grip_ridge_dia_mm=gripRidgeDia,
                            grip_arc_distance_mm=gripArcDistance,
                            grip_count=gripCount)
                        if gripEdges and gripEdges.count > 0:
                            addAngleChamferToEdge(
                                component, gripEdges,
                                gripChamferSize, grip_chamfer_angle)
                    else:
                        # Standard: single 45° equal-distance chamfer
                        chamferEdge = findChamferEdge(
                            extrude, targetBody, item['parentSketch'],
                            item['center2d'], diameter)
                        if chamferEdge:
                            addChamferToEdge(component, chamferEdge, tm_state.CONFIG['chamfer_size'])

                if includeBottomRadius:
                    addBottomRadiusToBlindHole(
                        component, extrude, targetBody, item['parentSketch'],
                        item['center2d'], diameter, tm_state.CONFIG['bottom_radius_size']
                    )

                successCount += 1

            if successCount > 0 and timeline is not None and startIndex >= 0:
                try:
                    endIndex = timeline.markerPosition - 1
                    if endIndex >= startIndex:
                        timelineGroup = timeline.timelineGroups.add(startIndex, endIndex)
                        timelineGroup.name = f'({successCount}x {insertName})'
                except Exception as e:
                    tm_helpers.log(f'Timeline grouping failed: {e}')

            if failedCount > 0:
                details = summarise_failures(failures)
                tm_state._ui.messageBox(
                    f'Created {successCount} insert hole(s), {failedCount} failed.\n\n{details}'
                )
            elif showMessage:
                tm_state._ui.messageBox(f'Successfully created {successCount} insert hole(s).')

        except Exception:
            tm_state._ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))
