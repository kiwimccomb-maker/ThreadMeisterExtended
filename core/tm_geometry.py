"""
tm_geometry.py – All geometry functions: profile finding, extrusion direction,
chamfer, fillet, through-body distance, and grip-ridge sketch generation.
"""
import adsk.core, adsk.fusion, traceback
import math
from itertools import combinations
import tm_helpers
import tm_state

# Profile point margin: profiles must have ALL endpoints within circle_radius * (1 + this margin)
PROFILE_POINT_MARGIN = 0.05


def _filter_by_area(sketch, target_area):
    """
    Coarse area filter: select profiles whose area <= target_area * 1.01.

    Returns:
        List of (profile, area) tuples passing the area filter.
    """
    candidates = []
    threshold = target_area * 1.01
    for idx, prof in enumerate(sketch.profiles):
        props = prof.areaProperties(adsk.fusion.CalculationAccuracy.MediumCalculationAccuracy)
        if props.area <= threshold:
            candidates.append((prof, props.area))
    return candidates


def _filter_by_centroid(candidates, circle_center3d, circle_radius):
    """
    Coarse centroid filter: check if profile centroid is inside target circle.

    Args:
        candidates: List of (profile, area) tuples from area filter
        circle_center3d: 3D center point of target circle
        circle_radius: Radius of target circle

    Returns:
        List of (profile, area, centroid_distance) tuples passing centroid filter.
    """
    filtered = []
    for idx, (prof, area) in enumerate(candidates):
        props = prof.areaProperties(adsk.fusion.CalculationAccuracy.MediumCalculationAccuracy)
        centroid3d = props.centroid
        distance = circle_center3d.distanceTo(centroid3d)

        if distance <= circle_radius:
            filtered.append((prof, area, distance))

    return filtered


def _filter_by_curve_points(candidates, circle_center3d, circle_radius):
    """
    Geometric curve-point filter: check if all sketch entity endpoints are inside target circle.

    For each profile's sketch curves, this filter verifies that:
    - All non-construction curve endpoints (start/end for lines/arcs, center for circles)
      lie within circle_radius * (1 + PROFILE_POINT_MARGIN)
    - If no non-construction curves exist, falls back to centroid check

    Args:
        candidates: List of (profile, area, distance) tuples from centroid filter
        circle_center3d: 3D center point of target circle
        circle_radius: Radius of target circle

    Returns:
        List of (profile, area, distance) tuples passing curve-point filter.
    """
    filtered = []
    acceptance_radius = circle_radius * (1 + PROFILE_POINT_MARGIN)

    for idx, (prof, area, centroid_distance) in enumerate(candidates):
        all_points_inside = True
        has_non_construction = False

        try:
            for loop in prof.profileLoops:
                for profile_curve in loop.profileCurves:
                    sketch_entity = profile_curve.sketchEntity

                    # Skip construction and projected/reference entities
                    if sketch_entity.isConstruction:
                        continue
                    if getattr(sketch_entity, 'isReference', False):
                        continue

                    has_non_construction = True
                    points_to_check = []

                    if isinstance(sketch_entity, adsk.fusion.SketchLine):
                        start_pt = sketch_entity.startSketchPoint.geometry
                        end_pt = sketch_entity.endSketchPoint.geometry
                        points_to_check = [start_pt, end_pt]

                    elif isinstance(sketch_entity, adsk.fusion.SketchArc):
                        center_pt = sketch_entity.centerSketchPoint.geometry
                        start_pt = sketch_entity.startSketchPoint.geometry
                        end_pt = sketch_entity.endSketchPoint.geometry
                        points_to_check = [center_pt, start_pt, end_pt]

                    elif isinstance(sketch_entity, adsk.fusion.SketchCircle):
                        center_pt = sketch_entity.centerSketchPoint.geometry
                        points_to_check = [center_pt]

                    elif isinstance(sketch_entity, adsk.fusion.SketchEllipticalArc):
                        center_pt = sketch_entity.centerSketchPoint.geometry
                        start_pt = sketch_entity.startSketchPoint.geometry
                        end_pt = sketch_entity.endSketchPoint.geometry
                        points_to_check = [center_pt, start_pt, end_pt]

                    elif isinstance(sketch_entity, adsk.fusion.SketchEllipse):
                        center_pt = sketch_entity.centerSketchPoint.geometry
                        points_to_check = [center_pt]

                    for pt in points_to_check:
                        distance = circle_center3d.distanceTo(pt)
                        if distance > acceptance_radius:
                            all_points_inside = False
                            break

                    if not all_points_inside:
                        break

                if not all_points_inside:
                    break

        except Exception:
            tm_helpers.log('Error in _filter_by_curve_points: {}'.format(traceback.format_exc()))
            has_non_construction = False

        if not has_non_construction:
            filtered.append((prof, area, centroid_distance))
        elif all_points_inside:
            filtered.append((prof, area, centroid_distance))

    return filtered


def _filter_by_bounding_box(candidates, circle_center3d, circle_radius):
    """
    Coarse bounding box filter: check if profile bbox fits in generous circle area.

    Args:
        candidates: List of (profile, area, distance) tuples from centroid filter
        circle_center3d: 3D center point of target circle
        circle_radius: Radius of target circle

    Returns:
        List of (profile, area, distance) tuples passing bbox filter.
    """
    bbox_margin = circle_radius * 0.1
    circle_bbox_min_x = circle_center3d.x - circle_radius - bbox_margin
    circle_bbox_max_x = circle_center3d.x + circle_radius + bbox_margin
    circle_bbox_min_y = circle_center3d.y - circle_radius - bbox_margin
    circle_bbox_max_y = circle_center3d.y + circle_radius + bbox_margin

    filtered = []
    for prof, area, distance in candidates:
        prof_bbox = prof.boundingBox
        is_contained = (
            prof_bbox.minPoint.x >= circle_bbox_min_x and
            prof_bbox.maxPoint.x <= circle_bbox_max_x and
            prof_bbox.minPoint.y >= circle_bbox_min_y and
            prof_bbox.maxPoint.y <= circle_bbox_max_y
        )

        if is_contained:
            filtered.append((prof, area, distance))
    return filtered


def _accumulate_profiles(candidates, target_area):
    """
    Precise area matching: find profile combination with area closest to target.
    Uses combinatorial search with 15-profile cap.

    Args:
        candidates: List of (profile, area, distance) tuples from bbox filter
        target_area: Target circle area

    Returns:
        (best_profiles, best_difference) tuple, or (None, inf) if no match.
    """
    candidates.sort(key=lambda x: x[1], reverse=True)

    best_profiles = None
    best_difference = float('inf')
    max_profiles = min(len(candidates), 15)

    for r in range(1, max_profiles + 1):
        for combo in combinations(candidates, r):
            combo_area = sum(item[1] for item in combo)
            difference = abs(combo_area - target_area)

            if difference < best_difference:
                best_difference = difference
                best_profiles = [item[0] for item in combo]

            if best_difference <= target_area * 0.00003:
                break

        if best_difference <= target_area * 0.00003:
            break

    return best_profiles, best_difference


def findProfileForCircle(sketch, target_circle):
    """
    Find all profiles that make up the area inside the target circle.

    Strategy:
    1. Coarse filters to reduce candidates (fast, permissive)
       - Area: not larger than circle
       - Centroid: inside circle
    2. Precise area-matching to find exact combination (slow, accurate)

    Returns:
        Profile, ObjectCollection of profiles, or None if validation fails.
    """
    if target_circle.parentSketch != sketch:
        return None

    circle_center3d = target_circle.centerSketchPoint.geometry
    circle_radius = target_circle.radius
    target_area = target_circle.area

    candidates_after_area = _filter_by_area(sketch, target_area)
    if not candidates_after_area:
        return None

    candidates_after_centroid = _filter_by_centroid(candidates_after_area, circle_center3d, circle_radius)
    if not candidates_after_centroid:
        return None

    candidates_after_curve = _filter_by_curve_points(candidates_after_centroid, circle_center3d, circle_radius)
    if not candidates_after_curve:
        return None

    best_profiles, best_difference = _accumulate_profiles(candidates_after_curve, target_area)

    if best_profiles is None:
        return None

    tolerance = target_area * 0.03
    if best_difference > tolerance:
        return None

    if len(best_profiles) == 1:
        return best_profiles[0]

    coll = adsk.core.ObjectCollection.create()
    for prof in best_profiles:
        coll.add(prof)
    return coll


def findExtrudeDirectionFromSketch(sketch, circleCenter, targetBody):
    """
    Determine extrude direction by checking which side of the sketch plane
    enters the target body.

    Returns:
        adsk.fusion.ExtentDirections enum value, or None on failure
    """
    try:
        sketchTransform = sketch.transform
        center3DSketch = adsk.core.Point3D.create(circleCenter.x, circleCenter.y, 0)
        center3D = center3DSketch.copy()
        center3D.transformBy(sketchTransform)

        (origin, xAxis, yAxis, zAxis) = sketchTransform.getAsCoordinateSystem()

        testDistances = [0.01, 0.05, 0.1, 0.2]

        positiveIsInside = False
        negativeIsInside = False

        for testDistance in testDistances:
            positivePoint = adsk.core.Point3D.create(
                center3D.x + zAxis.x * testDistance,
                center3D.y + zAxis.y * testDistance,
                center3D.z + zAxis.z * testDistance
            )
            positiveContainment = targetBody.pointContainment(positivePoint)
            if (positiveContainment == adsk.fusion.PointContainment.PointInsidePointContainment or
                    positiveContainment == adsk.fusion.PointContainment.PointOnPointContainment):
                positiveIsInside = True
                break

        for testDistance in testDistances:
            negativePoint = adsk.core.Point3D.create(
                center3D.x - zAxis.x * testDistance,
                center3D.y - zAxis.y * testDistance,
                center3D.z - zAxis.z * testDistance
            )
            negativeContainment = targetBody.pointContainment(negativePoint)
            if (negativeContainment == adsk.fusion.PointContainment.PointInsidePointContainment or
                    negativeContainment == adsk.fusion.PointContainment.PointOnPointContainment):
                negativeIsInside = True
                break

        if positiveIsInside and not negativeIsInside:
            return adsk.fusion.ExtentDirections.PositiveExtentDirection
        elif negativeIsInside and not positiveIsInside:
            return adsk.fusion.ExtentDirections.NegativeExtentDirection
        elif positiveIsInside and negativeIsInside:
            verySmallDistance = 0.001

            veryClosePositive = adsk.core.Point3D.create(
                center3D.x + zAxis.x * verySmallDistance,
                center3D.y + zAxis.y * verySmallDistance,
                center3D.z + zAxis.z * verySmallDistance
            )
            veryCloseNegative = adsk.core.Point3D.create(
                center3D.x - zAxis.x * verySmallDistance,
                center3D.y - zAxis.y * verySmallDistance,
                center3D.z - zAxis.z * verySmallDistance
            )

            posContain = targetBody.pointContainment(veryClosePositive)
            negContain = targetBody.pointContainment(veryCloseNegative)

            posOut = (posContain == adsk.fusion.PointContainment.PointOutsidePointContainment)
            negOut = (negContain == adsk.fusion.PointContainment.PointOutsidePointContainment)

            if posOut and not negOut:
                return adsk.fusion.ExtentDirections.NegativeExtentDirection
            elif negOut and not posOut:
                return adsk.fusion.ExtentDirections.PositiveExtentDirection
            else:
                return adsk.fusion.ExtentDirections.PositiveExtentDirection
        else:
            return None

    except Exception:
        msg = 'Error in findExtrudeDirectionFromSketch:\n{}'.format(traceback.format_exc())
        tm_helpers.log(msg)
        if tm_state._ui:
            tm_state._ui.messageBox(msg)
        return None


def findChamferEdge(extrudeFeature, targetBody, sketch, circleCenter, holeDiameter):
    """
    Find the circular edge at the hole entrance for chamfering.

    Returns:
        The edge to chamfer, or None if not found
    """
    try:
        sketchTransform = sketch.transform
        center3DSketch = adsk.core.Point3D.create(circleCenter.x, circleCenter.y, 0)
        center3D = center3DSketch.copy()
        center3D.transformBy(sketchTransform)

        (origin, xAxis, yAxis, zAxis) = sketchTransform.getAsCoordinateSystem()

        expectedRadius = holeDiameter / 2.0
        candidateEdges = []

        for edge in targetBody.edges:
            if edge.geometry.curveType == adsk.core.Curve3DTypes.Circle3DCurveType:
                edgeCircle = edge.geometry
                edgeCenter = edgeCircle.center
                edgeRadius = edgeCircle.radius
                edgeNormal = edgeCircle.normal

                if abs(edgeRadius - expectedRadius) > 0.001:
                    continue

                dotProduct = abs(edgeNormal.x * zAxis.x + edgeNormal.y * zAxis.y + edgeNormal.z * zAxis.z)
                if dotProduct < 0.99:
                    continue

                vecToEdge = adsk.core.Vector3D.create(
                    edgeCenter.x - center3D.x,
                    edgeCenter.y - center3D.y,
                    edgeCenter.z - center3D.z
                )
                projection = vecToEdge.x * zAxis.x + vecToEdge.y * zAxis.y + vecToEdge.z * zAxis.z
                perpDist = vecToEdge.length - abs(projection)
                if perpDist > 0.01:
                    continue

                candidateEdges.append((edge, abs(projection)))

        if len(candidateEdges) > 0:
            candidateEdges.sort(key=lambda x: x[1])
            return candidateEdges[0][0]

        return None

    except Exception:
        msg = 'Error in findChamferEdge:\n{}'.format(traceback.format_exc())
        tm_helpers.log(msg)
        if tm_state._ui:
            tm_state._ui.messageBox(msg)
        return None


def getGripRidgeChamferEdges(extrudeFeature, targetBody, referenceSketch, referencePoint2d, nominal_dia_mm):
    """
    Find the 3 grip ridge arc edges at the hole entrance for chamfering.

    Steps:
    1. Find all Arc3D/Circle3D edges on the target body coplanar with the sketch plane
    2. Narrow to edges at distance ~0 from the sketch plane
    3. Filter by radius: only keep arcs matching the grip ridge circle radius
       from the GRIP_RIDGE_INSERTS spec (arc radius = 0.5 * nominal_dia / 2)
    4. Return the matching edges (should be 3)

    Args:
        extrudeFeature: The extrude feature (unused, kept for API compatibility)
        targetBody: The body that was cut.
        referenceSketch: The temp sketch on the hole face.
        referencePoint2d: The projected sketch point geometry (2D, in sketch coords).
        nominal_dia_mm: The nominal thread diameter in mm from GRIP_RIDGE_INSERTS.

    Returns:
        ObjectCollection of 3 grip ridge edges, or None.
    """
    try:
        # 1. Get 3D center and sketch plane normal
        center3DSketch = adsk.core.Point3D.create(
            referencePoint2d.x, referencePoint2d.y, 0.0)
        center3D = center3DSketch.copy()
        center3D.transformBy(referenceSketch.transform)

        (_origin, _xAxis, _yAxis, zAxis) = referenceSketch.transform.getAsCoordinateSystem()

        # Expected grip ridge arc radius in cm (Fusion internal units).
        # Matches create_grip_ridge_sketch: arc_circle_dia = 0.5 * nominal_dia_mm
        # so radius = arc_circle_dia / 2 = 0.25 * nominal_dia_mm, then /10 for cm.
        expected_grip_radius_cm = (0.5 * nominal_dia_mm) / 2.0 / 10.0

        radius_tol = 0.005    # 0.05 mm in cm
        plane_tol = 0.005     # 0.05 mm in cm

        # 2. Scan all edges on the target body
        total_edges = targetBody.edges.count
        tm_helpers.log('GripRidgeChamfer: total body edges = {}'.format(total_edges))

        matching_edges = []
        arc_count = 0
        circle_count = 0
        parallel_count = 0
        coplanar_count = 0
        radius_match_count = 0

        for edge in targetBody.edges:
            # Accept both Arc3D and Circle3D (trimmed circles may be either type)
            if edge.geometry.curveType == adsk.core.Curve3DTypes.Arc3DCurveType:
                arc_count += 1
            elif edge.geometry.curveType == adsk.core.Curve3DTypes.Circle3DCurveType:
                circle_count += 1
            else:
                continue

            curve = edge.geometry
            edge_center = curve.center
            edge_normal = curve.normal
            edge_radius = curve.radius

            # Must be parallel to sketch plane
            dot = abs(edge_normal.x * zAxis.x +
                      edge_normal.y * zAxis.y +
                      edge_normal.z * zAxis.z)
            if dot < 0.99:
                continue
            parallel_count += 1

            # Must be coplanar with the sketch plane (distance ~0)
            vec = adsk.core.Vector3D.create(
                edge_center.x - center3D.x,
                edge_center.y - center3D.y,
                edge_center.z - center3D.z)
            projection = vec.x * zAxis.x + vec.y * zAxis.y + vec.z * zAxis.z
            perp_dist_sq = vec.length ** 2 - projection ** 2
            if perp_dist_sq < 0:
                perp_dist = 0.0
            else:
                perp_dist = math.sqrt(perp_dist_sq)

            if abs(projection) > plane_tol or perp_dist > plane_tol:
                continue
            coplanar_count += 1

            # 3. Match radius against expected grip ridge radius
            tm_helpers.log('  Coplanar edge: radius={:.6f} cm (expected={:.6f}, diff={:.6f})'.format(
                edge_radius, expected_grip_radius_cm, abs(edge_radius - expected_grip_radius_cm)))

            if abs(edge_radius - expected_grip_radius_cm) > radius_tol:
                continue
            radius_match_count += 1

            matching_edges.append(edge)

        # Diagnostic summary
        tm_helpers.log('GripRidgeChamfer diagnostics:')
        tm_helpers.log('  Arc edges={}, Circle edges={}'.format(arc_count, circle_count))
        tm_helpers.log('  Parallel to plane={}'.format(parallel_count))
        tm_helpers.log('  Coplanar (dist~0)={}'.format(coplanar_count))
        tm_helpers.log('  Radius match={}'.format(radius_match_count))
        tm_helpers.log('  Total matching={}'.format(len(matching_edges)))
        tm_helpers.log('  Expected radius={} cm (nominal_dia={} mm)'.format(
            expected_grip_radius_cm, nominal_dia_mm))

        if len(matching_edges) < 3:
            if tm_state._ui:
                tm_state._ui.messageBox(
                    'Grip ridge chamfer: found {} matching edges (need 3).\n'
                    'Expected radius: {:.4f} cm\n'
                    'Arc edges: {}, Circle edges: {}, Parallel: {}, Coplanar: {}, Radius match: {}\n'
                    'Check tm_helpers log for details.'.format(
                        len(matching_edges), expected_grip_radius_cm,
                        arc_count, circle_count, parallel_count, coplanar_count, radius_match_count))
            return None

        # 4. Return exactly the first 3 matching edges
        result = adsk.core.ObjectCollection.create()
        for edge in matching_edges[:3]:
            result.add(edge)

        tm_helpers.log('GripRidgeChamfer: returning {} edges'.format(result.count))
        return result

    except Exception:
        msg = 'Error in getGripRidgeChamferEdges:\n{}'.format(traceback.format_exc())
        tm_helpers.log(msg)
        if tm_state._ui:
            tm_state._ui.messageBox(msg)
        return None


def addChamferToEdge(component, edge, chamferSize):
    """
    Add a 45-degree equal-distance chamfer to the specified edge.

    Returns:
        The chamfer feature, or None if failed
    """
    try:
        chamfers = component.features.chamferFeatures
        edges = adsk.core.ObjectCollection.create()
        edges.add(edge)
        chamferInput = chamfers.createInput(edges, False)
        chamferDistance = adsk.core.ValueInput.createByReal(chamferSize / 10.0)
        chamferInput.setToEqualDistance(chamferDistance)
        chamfer = chamfers.add(chamferInput)
        return chamfer
    except Exception:
        return None


def addAngleChamferToEdge(component, edge, chamferSize, angleDeg):
    """
    Add a chamfer with a specified distance and angle to the specified edge(s).

    Args:
        component: Fusion 360 Component
        edge: A single edge OR an ObjectCollection of edges to chamfer
        chamferSize: Distance along the face in mm
        angleDeg: Chamfer angle in degrees (measured from the face plane)

    Returns:
        The chamfer feature, or None if failed
    """
    try:
        if edge is None:
            return None

        chamfers = component.features.chamferFeatures

        # Accept either a single edge or an ObjectCollection
        if isinstance(edge, adsk.core.ObjectCollection):
            edges = edge
        else:
            edges = adsk.core.ObjectCollection.create()
            edges.add(edge)

        chamferInput = chamfers.createInput(edges, False)
        chamferDistance = adsk.core.ValueInput.createByReal(chamferSize / 10.0)
        angleRad = math.radians(angleDeg)
        angleValue = adsk.core.ValueInput.createByReal(angleRad)
        chamferInput.setToDistanceAndAngle(chamferDistance, angleValue)

        chamfer = chamfers.add(chamferInput)
        return chamfer
    except Exception:
        return None


def findDistanceThroughBody(sketch, circleCenter, targetBody, direction):
    """
    Find the distance to cut completely through the body in the given direction.

    Returns:
        Distance in cm, or fallback of 10.0 cm
    """
    try:
        sketchTransform = sketch.transform
        center3DSketch = adsk.core.Point3D.create(circleCenter.x, circleCenter.y, 0)
        center3D = center3DSketch.copy()
        center3D.transformBy(sketchTransform)

        (origin, xAxis, yAxis, zAxis) = sketchTransform.getAsCoordinateSystem()

        multiplier = 1.0 if direction == adsk.fusion.ExtentDirections.PositiveExtentDirection else -1.0

        maxDistance = 100.0
        stepSize = 0.1

        insideBody = False
        exitDistance = None

        for i in range(1, int(maxDistance / stepSize) + 1):
            distance = i * stepSize
            testPoint = adsk.core.Point3D.create(
                center3D.x + zAxis.x * distance * multiplier,
                center3D.y + zAxis.y * distance * multiplier,
                center3D.z + zAxis.z * distance * multiplier
            )
            containment = targetBody.pointContainment(testPoint)
            if containment == adsk.fusion.PointContainment.PointInsidePointContainment:
                insideBody = True
            if insideBody and containment == adsk.fusion.PointContainment.PointOutsidePointContainment:
                exitDistance = distance
                break

        if exitDistance is not None:
            return exitDistance + 0.2

        return 10.0

    except Exception:
        msg = 'Error in findDistanceThroughBody:\n{}'.format(traceback.format_exc())
        tm_helpers.log(msg)
        if tm_state._ui:
            tm_state._ui.messageBox(msg)
        return 10.0


def addBottomRadiusToBlindHole(component, extrudeFeature, targetBody, sketch, circleCenter, holeDiameter, radiusSize):
    """
    Add a fillet to the bottom edge of a blind hole.

    Returns:
        The fillet feature, or None if failed
    """
    try:
        sketchTransform = sketch.transform
        center3DSketch = adsk.core.Point3D.create(circleCenter.x, circleCenter.y, 0)
        center3D = center3DSketch.copy()
        center3D.transformBy(sketchTransform)

        (origin, xAxis, yAxis, zAxis) = sketchTransform.getAsCoordinateSystem()

        expectedRadius = holeDiameter / 2.0
        filletRadiusCm = radiusSize / 10.0

        candidateEdges = []

        for edge in targetBody.edges:
            if edge.geometry.curveType != adsk.core.Curve3DTypes.Circle3DCurveType:
                continue

            edgeCircle = edge.geometry
            edgeCenter = edgeCircle.center
            edgeRadius = edgeCircle.radius
            edgeNormal = edgeCircle.normal

            if abs(edgeRadius - expectedRadius) > 0.005:
                continue

            dotProduct = abs(edgeNormal.x * zAxis.x + edgeNormal.y * zAxis.y + edgeNormal.z * zAxis.z)
            if dotProduct < 0.95:
                continue

            vecToEdge = adsk.core.Vector3D.create(
                edgeCenter.x - center3D.x,
                edgeCenter.y - center3D.y,
                edgeCenter.z - center3D.z
            )
            distanceAlongNormal = abs(vecToEdge.x * zAxis.x + vecToEdge.y * zAxis.y + vecToEdge.z * zAxis.z)
            perpDistanceSquared = (vecToEdge.length ** 2) - (distanceAlongNormal ** 2)
            perpDistance = math.sqrt(max(0, perpDistanceSquared))

            if perpDistance > 0.05:
                continue
            candidateEdges.append((edge, distanceAlongNormal))

        if len(candidateEdges) == 0:
            return None

        # Sort by distance: furthest = bottom of blind hole
        candidateEdges.sort(key=lambda x: x[1], reverse=True)
        bottomEdge = candidateEdges[0][0]

        fillets = component.features.filletFeatures
        edgeCollection = adsk.core.ObjectCollection.create()
        edgeCollection.add(bottomEdge)

        filletInput = fillets.createInput()

        try:
            filletInput.addConstantRadiusEdgeSet(
                edgeCollection,
                adsk.core.ValueInput.createByReal(filletRadiusCm),
                True
            )
        except Exception:
            return None

        try:
            fillet = fillets.add(filletInput)
            return fillet if fillet else None
        except Exception:
            return None

    except Exception:
        msg = 'Error in addBottomRadiusToBlindHole:\n{}'.format(traceback.format_exc())
        tm_helpers.log(msg)
        if tm_state._ui:
            tm_state._ui.messageBox(msg)
        return None


def create_grip_ridge_sketch(sketch, center_point_2d, clearance_dia_mm, nominal_dia_mm):
    """
    Create a grip-ridge insert profile in the given sketch.

    Draws a central clearance hole and three arc grip ridges at 120° intervals.
    Each arc circle has diameter = 0.5 * nominal_dia_mm, centred at distance
    0.6 * nominal_dia_mm from the centre.

    Args:
        sketch: Fusion 360 Sketch object
        center_point_2d: Point2D at the sketch centre
        clearance_dia_mm: Clearance hole diameter in mm
        nominal_dia_mm: Nominal (major) thread diameter in mm

    Returns:
        The combined profile (largest profile containing the centre point),
        or None if not found.
    """
    try:
        # Convert mm to cm (Fusion internal units)
        clearance_radius = clearance_dia_mm / 2.0 / 10.0

        arc_circle_dia = 0.5 * nominal_dia_mm
        arc_circle_radius = arc_circle_dia / 2.0 / 10.0
        arc_center_distance = 0.6 * nominal_dia_mm / 10.0

        # Draw central clearance hole circle
        sketch.sketchCurves.sketchCircles.addByCenterRadius(
            center_point_2d, clearance_radius)

        # Draw three arc grip ridge circles at 0°, 120°, 240°
        grip_circles = []
        for angle_deg in (0.0, 120.0, 240.0):
            angle_rad = math.radians(angle_deg)
            arc_x = center_point_2d.x + arc_center_distance * math.cos(angle_rad)
            arc_y = center_point_2d.y + arc_center_distance * math.sin(angle_rad)
            arc_center = adsk.core.Point3D.create(arc_x, arc_y, 0.0)
            circle = sketch.sketchCurves.sketchCircles.addByCenterRadius(
                arc_center, arc_circle_radius)
            grip_circles.append((circle, angle_deg))

        # Trim each grip ridge circle against the clearance circle.
        # After trimming, each full circle becomes an arc segment representing
        # only the portion that extends OUTSIDE the clearance circle.
        # This creates clean, separable arc ridge edges that can be chamfered.
        for circle, angle_deg in grip_circles:
            angle_rad = math.radians(angle_deg)
            # Point in the middle of the outer arc (furthest from hole center)
            outer_dist = arc_center_distance + arc_circle_radius * 0.5
            outer_x = center_point_2d.x + outer_dist * math.cos(angle_rad)
            outer_y = center_point_2d.y + outer_dist * math.sin(angle_rad)
            outer_point = adsk.core.Point3D.create(outer_x, outer_y, 0.0)
            try:
                sketch.sketchCurves.trim(circle, outer_point)
            except Exception:
                # Trim may fail if the intersection is degenerate; skip that circle
                pass

        # Find the combined profile: the largest profile whose centroid is
        # very close to the centre point (the union of all overlapping circles)
        centre_3d = adsk.core.Point3D.create(
            center_point_2d.x, center_point_2d.y, 0.0)

        best_profile = None
        best_area = 0.0

        for prof in sketch.profiles:
            props = prof.areaProperties(
                adsk.fusion.CalculationAccuracy.MediumCalculationAccuracy)
            centroid = props.centroid
            dist = centre_3d.distanceTo(centroid)

            # Accept only profiles whose centroid is within 0.1 mm of centre
            if dist < 0.01 and props.area > best_area:
                best_area = props.area
                best_profile = prof

        return best_profile

    except Exception:
        msg = 'Error in create_grip_ridge_sketch:\n{}'.format(traceback.format_exc())
        tm_helpers.log(msg)
        if tm_state._ui:
            tm_state._ui.messageBox(msg)
        return None
