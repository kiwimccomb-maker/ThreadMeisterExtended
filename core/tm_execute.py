"""
tm_execute.py – CommandExecuteHandler: orchestrates the hole creation loop.
"""
import adsk.core, adsk.fusion, traceback, os
import tm_helpers
import tm_state
import tm_config
from tm_helpers import calc_blind_hole_depth_mm
from tm_geometry import (
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


class CommandExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            bodySelect = inputs.itemById('bodySelect')
            pointSelect = inputs.itemById('pointSelect')
            insertSize = inputs.itemById('insertSize')
            holeType = inputs.itemById('holeType')
            addChamfer = inputs.itemById('addChamfer')
            addBottomRadius = inputs.itemById('addBottomRadius')
            exportDebugInput = inputs.itemById('exportDebug')
            gripEdgeDepthInput = inputs.itemById('gripEdgeDepth')
            shouldExport = exportDebugInput is not None and exportDebugInput.value

            targetBody = bodySelect.selection(0).entity
            selectedPoints = [pointSelect.selection(i).entity for i in range(pointSelect.selectionCount)]

            insertName = insertSize.selectedItem.name
            tm_config.save_last_selected_insert(insertName)

            isBlindHole = holeType.selectedItem.name == 'Blind Hole'
            includeChamfer = addChamfer.value if addChamfer else tm_state.CONFIG.get('chamfer_enabled_default', True)
            includeBottomRadius = (addBottomRadius.value if addBottomRadius else tm_state.CONFIG.get('bottom_radius_enabled_default', False)) and isBlindHole
            showMessage = tm_state.CONFIG.get('show_success_message', True)

            tm_config.save_checkbox_states(includeChamfer, includeBottomRadius, showMessage, isBlindHole)

            is_grip_ridge = insertName in tm_state.GRIP_RIDGE_INSERTS

            if is_grip_ridge:
                clearanceDia, configInsertLen, minWall, nominalDia, _ = tm_state.GRIP_RIDGE_INSERTS[insertName]
                # Pre-calculate the default total depth (insert + extra depth)
                # Chamfer is applied to the edge AFTER extrusion, not part of hole depth
                configDepth = configInsertLen + tm_state.CONFIG['blind_hole_extra_depth']
                # Use spinner value if present and visible, otherwise calculated default
                # Note: gripEdgeDepthInput.value is in cm (Fusion's internal unit), convert to mm
                if gripEdgeDepthInput is not None and gripEdgeDepthInput.isVisible:
                    insertLen = gripEdgeDepthInput.value * 10.0  # cm -> mm
                else:
                    insertLen = configDepth
                holeDia = clearanceDia
            else:
                holeDia, insertLen, minWall = tm_state.INSERT_SPECS[insertName]

            diameter = holeDia / 10.0   # mm -> cm

            successCount = 0
            failedCount = 0
            failMessages = []

            component = targetBody.parentComponent
            design = component.parentDesign
            timeline = None
            startIndex = -1

            if design and hasattr(design, 'timeline'):
                timeline = design.timeline
                if timeline and timeline.count > 0:
                    startIndex = timeline.markerPosition

            for point_idx, point in enumerate(selectedPoints):
                parentSketch = point.parentSketch
                center2d = point.geometry

                # Create clean sketch without auto-projected body edges
                face = parentSketch.referencePlane
                tempSketch = component.sketches.addWithoutEdges(face)
                tempSketch.name = f"TM_{insertName}_P{point_idx+1}"

                # Project original point to maintain parametric association
                projectedEntities = tempSketch.project(point)
                projectedPoint = projectedEntities.item(0)

                if is_grip_ridge:
                    profile_or_collection = create_grip_ridge_sketch(
                        tempSketch, projectedPoint.geometry, clearanceDia, nominalDia)
                    if profile_or_collection is None:
                        failedCount += 1
                        failMessages.append(
                            f'Point {point_idx+1}: Could not create grip-ridge profile.')
                        tempSketch.deleteMe()
                        continue
                else:
                    radius = holeDia / 2.0 / 10.0   # mm -> cm

                    # Create bore circle in clean sketch
                    circle = tempSketch.sketchCurves.sketchCircles.addByCenterRadius(
                        projectedPoint.geometry, radius)
                    tempConstraints = tempSketch.geometricConstraints
                    tempConstraints.addCoincident(circle.centerSketchPoint, projectedPoint)

                    profile_or_collection = findProfileForCircle(tempSketch, circle)

                    if profile_or_collection is None:
                        failedCount += 1
                        failMessages.append(
                            f'Point {point_idx+1}: Could not create bore profile.')
                        tempSketch.deleteMe()
                        continue

                # Export debug JSON if enabled
                if shouldExport:
                    try:
                        from tm_debug_export import export_sketch_data
                        export_dir = os.path.join(
                            os.path.dirname(os.path.dirname(__file__)), 'debug_exports')
                        os.makedirs(export_dir, exist_ok=True)
                        target_circle = None
                        if is_grip_ridge:
                            for circle_candidate in tempSketch.sketchCurves.sketchCircles:
                                if circle_candidate.centerSketchPoint.geometry.distanceTo(projectedPoint.geometry) < 1e-6:
                                    target_circle = circle_candidate
                                    break
                            if target_circle is None:
                                tm_helpers.log(f'Grip-ridge debug export skipped: central circle not found for point {point_idx+1}')
                        else:
                            target_circle = circle

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
                    failMessages.append(f'Point {point_idx+1}: Could not determine extrusion direction. Ensure the sketch is on a planar face of the target body.')
                    tempSketch.deleteMe()
                    continue

                extrudes = component.features.extrudeFeatures
                extInput = extrudes.createInput(profile_or_collection, adsk.fusion.FeatureOperations.CutFeatureOperation)

                if isBlindHole:
                    if is_grip_ridge:
                        # Grip-ridge: spinner value is in cm (Fusion's internal unit), convert to mm
                        if gripEdgeDepthInput is not None and gripEdgeDepthInput.isVisible:
                            depth_mm = gripEdgeDepthInput.value * 10.0  # cm -> mm
                        else:
                            depth_mm = configDepth  # already in mm
                    else:
                        # Standard: insert length + extra depth + chamfer
                        chamfer = tm_state.CONFIG['chamfer_size'] if includeChamfer else 0.0
                        depth_mm = calc_blind_hole_depth_mm(
                            insertLen, tm_state.CONFIG['blind_hole_extra_depth'], chamfer)
                    holeDepth = depth_mm / 10.0  # mm -> cm
                    dist = adsk.core.ValueInput.createByReal(holeDepth)
                    extent = adsk.fusion.DistanceExtentDefinition.create(dist)
                    extInput.setOneSideExtent(extent, direction)
                else:
                    throughDistance = findDistanceThroughBody(parentSketch, center2d, targetBody, direction)
                    dist = adsk.core.ValueInput.createByReal(throughDistance)
                    extent = adsk.fusion.DistanceExtentDefinition.create(dist)
                    extInput.setOneSideExtent(extent, direction)

                extInput.participantBodies = [targetBody]
                extrude = extrudes.add(extInput)

                if includeChamfer:
                    if is_grip_ridge:
                        # Grip-ridge: chamfer every entrance edge with the configured chamfer size.
                        grip_chamfer_angle = tm_state.CONFIG.get('grip_chamfer_angle', 60)
                        gripEdges = getGripRidgeChamferEdges(
                            extrude, targetBody, tempSketch, projectedPoint.geometry)
                        if gripEdges and gripEdges.count > 0:
                            addAngleChamferToEdge(
                                component, gripEdges,
                                tm_state.CONFIG['chamfer_size'], grip_chamfer_angle)
                    else:
                        # Standard: single 45° equal-distance chamfer
                        chamferEdge = findChamferEdge(extrude, targetBody, parentSketch, center2d, diameter)
                        if chamferEdge:
                            addChamferToEdge(component, chamferEdge, tm_state.CONFIG['chamfer_size'])

                if includeBottomRadius:
                    addBottomRadiusToBlindHole(
                        component, extrude, targetBody, parentSketch, center2d,
                        diameter, tm_state.CONFIG['bottom_radius_size']
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
                details = '\n'.join(failMessages)
                tm_state._ui.messageBox(
                    f'Created {successCount} insert hole(s), {failedCount} failed.\n\n{details}'
                )
            elif showMessage:
                tm_state._ui.messageBox(f'Successfully created {successCount} insert hole(s).')

        except Exception:
            tm_state._ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))
