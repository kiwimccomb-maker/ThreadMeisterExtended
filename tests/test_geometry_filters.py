"""
Unit tests for tm_geometry.py filter functions.
"""

import pytest
import math
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock
import adsk
from tm_geometry import (
    _filter_by_area,
    _filter_by_centroid,
    _filter_by_bounding_box,
    _filter_by_curve_points,
    _accumulate_profiles,
    getGripRidgeChamferEdges,
    addAngleChamferToEdge,
)


# Fake sketch entity classes for isinstance() checks in tm_geometry
class FakeSketchLine:
    pass


class FakeSketchArc:
    pass


class FakeSketchCircle:
    pass


class FakeSketchEllipticalArc:
    pass


class FakeSketchEllipse:
    pass


def _register_fake_sketch_types():
    adsk.fusion.SketchLine = FakeSketchLine
    adsk.fusion.SketchArc = FakeSketchArc
    adsk.fusion.SketchCircle = FakeSketchCircle
    adsk.fusion.SketchEllipticalArc = FakeSketchEllipticalArc
    adsk.fusion.SketchEllipse = FakeSketchEllipse


_register_fake_sketch_types()


# Helper functions to create mock objects

def make_point(x, y, z=0.0):
    """Create a point object with x, y, z and distanceTo method."""
    point = SimpleNamespace(x=x, y=y, z=z)

    def distance_to(other):
        return math.sqrt(
            (point.x - other.x)**2 +
            (point.y - other.y)**2 +
            (point.z - other.z)**2
        )

    point.distanceTo = distance_to
    point.transformBy = lambda _transform: None
    return point


adsk.core.Point3D.create = lambda x, y, z=0.0: make_point(x, y, z)
adsk.core.Vector3D.create = lambda x, y, z=0.0: make_point(x, y, z)


def make_profile(area, centroid_x=0.0, centroid_y=0.0, centroid_z=0.0,
                 bbox_min_x=0.0, bbox_min_y=0.0, bbox_max_x=1.0, bbox_max_y=1.0):
    """Create a mock profile with areaProperties and boundingBox."""
    profile = MagicMock()

    # Mock areaProperties method
    area_props = MagicMock()
    area_props.area = area
    area_props.centroid = make_point(centroid_x, centroid_y, centroid_z)
    profile.areaProperties.return_value = area_props

    # Mock boundingBox
    bbox_min_point = MagicMock()
    bbox_min_point.x = bbox_min_x
    bbox_min_point.y = bbox_min_y

    bbox_max_point = MagicMock()
    bbox_max_point.x = bbox_max_x
    bbox_max_point.y = bbox_max_y

    profile.boundingBox = MagicMock()
    profile.boundingBox.minPoint = bbox_min_point
    profile.boundingBox.maxPoint = bbox_max_point

    return profile


class TestFilterByArea:
    """Test _filter_by_area function."""

    def test_profile_with_exact_target_area(self):
        """Profile with exact target area should be included."""
        target_area = 10.0
        profile = make_profile(area=10.0)

        # Create a mock sketch
        sketch = MagicMock()
        sketch.profiles = [profile]

        result = _filter_by_area(sketch, target_area)

        assert len(result) == 1
        assert result[0][0] == profile
        assert result[0][1] == 10.0

    def test_profile_within_1_percent_threshold(self):
        """Profile with area within 1% of target should be included."""
        target_area = 10.0
        profile = make_profile(area=10.09)  # 1.009 * target

        sketch = MagicMock()
        sketch.profiles = [profile]

        result = _filter_by_area(sketch, target_area)

        assert len(result) == 1

    def test_profile_exceeds_1_percent_threshold(self):
        """Profile with area >1% above target should be excluded."""
        target_area = 10.0
        profile = make_profile(area=10.11)  # > 1.01 * target

        sketch = MagicMock()
        sketch.profiles = [profile]

        result = _filter_by_area(sketch, target_area)

        assert len(result) == 0

    def test_multiple_profiles_filtered(self):
        """Filter multiple profiles by area."""
        target_area = 10.0
        # Threshold: target_area * 1.01 = 10.1
        profile1 = make_profile(area=9.5)       # < 10.1: included
        profile2 = make_profile(area=10.0)      # <= 10.1: included
        profile3 = make_profile(area=10.05)     # <= 10.1: included
        profile4 = make_profile(area=15.0)      # > 10.1: excluded

        sketch = MagicMock()
        sketch.profiles = [profile1, profile2, profile3, profile4]

        result = _filter_by_area(sketch, target_area)

        # profile1, profile2, profile3 should be included; profile4 excluded
        assert len(result) == 3
        assert profile1 in [p for p, _ in result]
        assert profile2 in [p for p, _ in result]
        assert profile3 in [p for p, _ in result]
        assert profile4 not in [p for p, _ in result]

    def test_empty_profiles(self):
        """Empty profile list should return empty."""
        sketch = MagicMock()
        sketch.profiles = []

        result = _filter_by_area(sketch, 10.0)

        assert len(result) == 0


class TestFilterByCentroid:
    """Test _filter_by_centroid function."""

    def test_centroid_at_circle_center(self):
        """Centroid at circle center should be included."""
        circle_center = make_point(0.0, 0.0, 0.0)
        circle_radius = 5.0

        profile = make_profile(area=10.0, centroid_x=0.0, centroid_y=0.0, centroid_z=0.0)
        candidates = [(profile, 10.0)]

        result = _filter_by_centroid(candidates, circle_center, circle_radius)

        assert len(result) == 1
        assert result[0][0] == profile

    def test_centroid_at_circle_edge(self):
        """Centroid at circle edge (distance == radius) should be included."""
        circle_center = make_point(0.0, 0.0, 0.0)
        circle_radius = 5.0

        # Centroid at distance 5.0 from center
        profile = make_profile(area=10.0, centroid_x=5.0, centroid_y=0.0, centroid_z=0.0)
        candidates = [(profile, 10.0)]

        result = _filter_by_centroid(candidates, circle_center, circle_radius)

        assert len(result) == 1

    def test_centroid_outside_circle(self):
        """Centroid outside circle should be excluded."""
        circle_center = make_point(0.0, 0.0, 0.0)
        circle_radius = 5.0

        # Centroid at distance 6.0 from center
        profile = make_profile(area=10.0, centroid_x=6.0, centroid_y=0.0, centroid_z=0.0)
        candidates = [(profile, 10.0)]

        result = _filter_by_centroid(candidates, circle_center, circle_radius)

        assert len(result) == 0

    def test_multiple_candidates_filtered(self):
        """Filter multiple candidates by centroid."""
        circle_center = make_point(0.0, 0.0, 0.0)
        circle_radius = 5.0

        profile1 = make_profile(area=5.0, centroid_x=0.0, centroid_y=0.0)
        profile2 = make_profile(area=6.0, centroid_x=3.0, centroid_y=4.0)  # distance 5.0
        profile3 = make_profile(area=7.0, centroid_x=4.0, centroid_y=4.0)  # distance ~5.66 > 5.0

        candidates = [(profile1, 5.0), (profile2, 6.0), (profile3, 7.0)]

        result = _filter_by_centroid(candidates, circle_center, circle_radius)

        assert len(result) == 2
        assert profile1 in [p for p, _, _ in result]
        assert profile2 in [p for p, _, _ in result]
        assert profile3 not in [p for p, _, _ in result]


# Helpers for curve point filter tests

def make_sketch_point(x, y, z=0.0):
    point = SimpleNamespace(x=x, y=y, z=z)
    point.distanceTo = lambda other: math.sqrt(
        (point.x - other.x)**2 +
        (point.y - other.y)**2 +
        (point.z - other.z)**2
    )
    return point


def make_sketch_line(start, end, is_construction=False, is_reference=False):
    sketch_entity = FakeSketchLine()
    sketch_entity.isConstruction = is_construction
    sketch_entity.isReference = is_reference
    sketch_entity.startSketchPoint = SimpleNamespace(geometry=start)
    sketch_entity.endSketchPoint = SimpleNamespace(geometry=end)
    profile_curve = MagicMock()
    profile_curve.sketchEntity = sketch_entity
    return profile_curve


def make_sketch_circle(center, is_construction=False, is_reference=False):
    sketch_entity = FakeSketchCircle()
    sketch_entity.isConstruction = is_construction
    sketch_entity.isReference = is_reference
    sketch_entity.centerSketchPoint = SimpleNamespace(geometry=center)
    profile_curve = MagicMock()
    profile_curve.sketchEntity = sketch_entity
    return profile_curve


class SimpleObjectCollection:
    def __init__(self):
        self._items = []

    def add(self, item):
        self._items.append(item)

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index]

    def __iter__(self):
        return iter(self._items)


class FakeGeometry:
    def __init__(self, surfaceType=None, curveType=None, origin=None, normal=None):
        self.surfaceType = surfaceType
        self.curveType = curveType
        self.origin = origin
        self.normal = normal


class FakeEdge:
    def __init__(self, curveType, length=1.0):
        self.geometry = FakeGeometry(curveType=curveType)
        self.length = length


class FakeFace:
    def __init__(self, surfaceType, edges, origin=None, normal=None):
        self.geometry = FakeGeometry(surfaceType=surfaceType, origin=origin, normal=normal)
        self.edges = edges


class FakeStartFaces:
    def __init__(self, faces):
        self._faces = faces

    @property
    def count(self):
        return len(self._faces)

    def item(self, index):
        return self._faces[index]


class FakeSketchTransform:
    def getAsCoordinateSystem(self):
        return (
            make_point(0.0, 0.0, 0.0),
            make_point(1.0, 0.0, 0.0),
            make_point(0.0, 1.0, 0.0),
            make_point(0.0, 0.0, 1.0),
        )


def make_reference_sketch():
    return SimpleNamespace(transform=FakeSketchTransform())


class TestFilterByCurvePoints:
    """Test _filter_by_curve_points function."""

    def test_profile_all_endpoints_inside_accepts(self):
        circle_center = make_point(0.0, 0.0, 0.0)
        circle_radius = 1.0
        acceptance_radius = circle_radius * 1.05

        start = make_sketch_point(0.5, 0.0)
        end = make_sketch_point(0.0, 0.5)
        profile = make_profile(area=1.0, centroid_x=0.0, centroid_y=0.0)
        loop = MagicMock()
        loop.profileCurves = [make_sketch_line(start, end)]
        profile.profileLoops = [loop]

        candidates = [(profile, 1.0, 0.0)]

        result = _filter_by_curve_points(candidates, circle_center, circle_radius)

        assert len(result) == 1
        assert result[0][0] == profile

    def test_getGripRidgeChamferEdges_selects_3_inner_arcs_by_geometry_match(self):
        """Test that arcs matching expected grip ridge geometry are selected."""
        # M3 grip: nominal_dia=3.0mm
        # Grip ridge radius = 0.5 * 3.0 / 2 = 0.75mm = 0.075cm
        expected_grip_radius = 0.075
        # Grip ridge center distance = 0.6 * 3.0 = 1.8mm = 0.18cm
        expected_center_dist = 0.18

        # 3 inner grip ridge arcs at 0°, 120°, 240° with correct geometry
        inner_arc1 = FakeEdge(
            curveType='Arc3DCurveType',
            length=2.0,
            geometry=SimpleNamespace(
                curveType='Arc3DCurveType',
                center=make_point(expected_center_dist, 0.0, 0.0),
                normal=make_point(0.0, 0.0, 1.0),
                radius=expected_grip_radius
            )
        )
        inner_arc2 = FakeEdge(
            curveType='Arc3DCurveType',
            length=2.0,
            geometry=SimpleNamespace(
                curveType='Arc3DCurveType',
                center=make_point(-0.09, 0.156, 0.0),  # 120° at expected_center_dist
                normal=make_point(0.0, 0.0, 1.0),
                radius=expected_grip_radius
            )
        )
        inner_arc3 = FakeEdge(
            curveType='Arc3DCurveType',
            length=2.0,
            geometry=SimpleNamespace(
                curveType='Arc3DCurveType',
                center=make_point(-0.09, -0.156, 0.0),  # 240° at expected_center_dist
                normal=make_point(0.0, 0.0, 1.0),
                radius=expected_grip_radius
            )
        )

        target_body = MagicMock()
        target_body.edges = [inner_arc1, inner_arc2, inner_arc3]

        extrude = MagicMock()
        reference_sketch = make_reference_sketch()
        reference_point = make_point(0.0, 0.0, 0.0)

        edges = getGripRidgeChamferEdges(extrude, target_body, reference_sketch, reference_point, nominal_dia_mm=3.0)

        # Should return the 3 grip ridge arcs matching expected geometry
        assert edges is not None
        assert edges.count == 3
        assert set(edges._items) == {inner_arc1, inner_arc2, inner_arc3}

    def test_getGripRidgeChamferEdges_excludes_unrelated_arcs(self):
        """Test that unrelated arcs on the same plane are excluded."""
        # M3 grip geometry
        expected_grip_radius = 0.075
        expected_center_dist = 0.18

        # Valid grip ridge arc
        grip_arc = FakeEdge(
            curveType='Arc3DCurveType',
            length=2.0,
            geometry=SimpleNamespace(
                curveType='Arc3DCurveType',
                center=make_point(expected_center_dist, 0.0, 0.0),
                normal=make_point(0.0, 0.0, 1.0),
                radius=expected_grip_radius
            )
        )
        # Unrelated arc on same plane but wrong radius
        wrong_radius_arc = FakeEdge(
            curveType='Arc3DCurveType',
            length=3.0,
            geometry=SimpleNamespace(
                curveType='Arc3DCurveType',
                center=make_point(0.5, 0.0, 0.0),
                normal=make_point(0.0, 0.0, 1.0),
                radius=0.2  # Wrong radius
            )
        )
        # Unrelated arc on same plane but wrong center position
        wrong_center_arc = FakeEdge(
            curveType='Arc3DCurveType',
            length=2.0,
            geometry=SimpleNamespace(
                curveType='Arc3DCurveType',
                center=make_point(5.0, 5.0, 0.0),  # Way off center
                normal=make_point(0.0, 0.0, 1.0),
                radius=expected_grip_radius
            )
        )

        target_body = MagicMock()
        target_body.edges = [grip_arc, wrong_radius_arc, wrong_center_arc]

        extrude = MagicMock()
        reference_sketch = make_reference_sketch()
        reference_point = make_point(0.0, 0.0, 0.0)

        edges = getGripRidgeChamferEdges(extrude, target_body, reference_sketch, reference_point, nominal_dia_mm=3.0)

        # Only the valid grip arc should match (but we need 3 for success)
        assert edges is None  # Fewer than 3 matching arcs

    def test_getGripRidgeChamferEdges_filters_by_sketch_plane(self):
        """Test that only arcs coplanar with the sketch plane are considered."""
        expected_grip_radius = 0.075
        expected_center_dist = 0.18

        top_arc1 = FakeEdge(
            curveType='Arc3DCurveType',
            length=2.0,
            geometry=SimpleNamespace(
                curveType='Arc3DCurveType',
                center=make_point(expected_center_dist, 0.0, 0.0),
                normal=make_point(0.0, 0.0, 1.0),
                radius=expected_grip_radius
            )
        )
        top_arc2 = FakeEdge(
            curveType='Arc3DCurveType',
            length=1.8,
            geometry=SimpleNamespace(
                curveType='Arc3DCurveType',
                center=make_point(-0.09, 0.156, 0.0),
                normal=make_point(0.0, 0.0, 1.0),
                radius=expected_grip_radius
            )
        )
        top_arc3 = FakeEdge(
            curveType='Arc3DCurveType',
            length=1.9,
            geometry=SimpleNamespace(
                curveType='Arc3DCurveType',
                center=make_point(-0.09, -0.156, 0.0),
                normal=make_point(0.0, 0.0, 1.0),
                radius=expected_grip_radius
            )
        )
        # Arc on bottom of hole (z=-1) - should be excluded
        bottom_arc = FakeEdge(
            curveType='Arc3DCurveType',
            length=2.0,
            geometry=SimpleNamespace(
                curveType='Arc3DCurveType',
                center=make_point(0.0, 0.0, -1.0),
                normal=make_point(0.0, 0.0, 1.0),
                radius=expected_grip_radius
            )
        )

        target_body = MagicMock()
        target_body.edges = [top_arc1, top_arc2, top_arc3, bottom_arc]

        extrude = MagicMock()
        reference_sketch = make_reference_sketch()
        reference_point = make_point(0.0, 0.0, 0.0)

        edges = getGripRidgeChamferEdges(extrude, target_body, reference_sketch, reference_point, nominal_dia_mm=3.0)

        # Should return only top arcs, not bottom arc
        assert edges is not None
        assert edges.count == 3
        assert set(edges._items) == {top_arc1, top_arc2, top_arc3}
        assert bottom_arc not in edges._items

    def test_getGripRidgeChamferEdges_returns_none_if_fewer_than_3(self):
        """Test that fewer than 3 matching arcs returns None."""
        expected_grip_radius = 0.075
        expected_center_dist = 0.18

        only_arc = FakeEdge(
            curveType='Arc3DCurveType',
            length=2.0,
            geometry=SimpleNamespace(
                curveType='Arc3DCurveType',
                center=make_point(expected_center_dist, 0.0, 0.0),
                normal=make_point(0.0, 0.0, 1.0),
                radius=expected_grip_radius
            )
        )

        target_body = MagicMock()
        target_body.edges = [only_arc]

        extrude = MagicMock()
        reference_sketch = make_reference_sketch()
        reference_point = make_point(0.0, 0.0, 0.0)

        edges = getGripRidgeChamferEdges(extrude, target_body, reference_sketch, reference_point, nominal_dia_mm=3.0)

        # Should return None if fewer than 3 matching arcs found
        assert edges is None

    def test_addAngleChamferToEdge_sets_distance_and_angle(self, monkeypatch):
        edge = FakeEdge(curveType='Circle3DCurveType', length=2.0)
        component = MagicMock()
        chamfer_features = MagicMock()
        component.features.chamferFeatures = chamfer_features

        chamfer_input = MagicMock()
        chamfer_output = MagicMock()
        chamfer_features.createInput.return_value = chamfer_input
        chamfer_features.add.return_value = chamfer_output

        created_values = []

        def create_by_real(value):
            created_values.append(value)
            return f'ValueInput({value})'

        monkeypatch.setattr('adsk.core.ValueInput.createByReal', create_by_real)

        result = addAngleChamferToEdge(component, edge, 0.5, 60)

        assert result is chamfer_output
        assert chamfer_features.createInput.called
        assert chamfer_input.setToDistanceAndAngle.called
        assert created_values[0] == 0.05
        assert math.isclose(created_values[1], math.radians(60), rel_tol=1e-9)

    def test_addAngleChamferToEdge_accepts_object_collection(self, monkeypatch):
        """Test that addAngleChamferToEdge accepts an ObjectCollection of edges."""
        edge1 = FakeEdge(curveType='Circle3DCurveType', length=2.0)
        edge2 = FakeEdge(curveType='Circle3DCurveType', length=1.8)
        edge3 = FakeEdge(curveType='Circle3DCurveType', length=1.9)

        component = MagicMock()
        chamfer_features = MagicMock()
        component.features.chamferFeatures = chamfer_features

        chamfer_input = MagicMock()
        chamfer_output = MagicMock()
        chamfer_features.createInput.return_value = chamfer_input
        chamfer_features.add.return_value = chamfer_output

        # Create a mock ObjectCollection
        mock_collection = MagicMock()
        mock_collection.count = 3

        # Patch ObjectCollection.create to return our mock
        original_create = adsk.core.ObjectCollection.create
        adsk.core.ObjectCollection.create = MagicMock(return_value=mock_collection)

        try:
            result = addAngleChamferToEdge(component, mock_collection, 0.5, 60)

            assert result is chamfer_output
            # Should use the collection directly, not create a new one
            assert adsk.core.ObjectCollection.create.call_count == 0
            assert chamfer_input.setToDistanceAndAngle.called
        finally:
            adsk.core.ObjectCollection.create = original_create

    def test_profile_endpoint_outside_rejects(self):
        circle_center = make_point(0.0, 0.0, 0.0)
        circle_radius = 1.0

        start = make_sketch_point(0.5, 0.0)
        end = make_sketch_point(1.2, 0.0)
        profile = make_profile(area=1.0, centroid_x=0.0, centroid_y=0.0)
        loop = MagicMock()
        loop.profileCurves = [make_sketch_line(start, end)]
        profile.profileLoops = [loop]

        candidates = [(profile, 1.0, 0.0)]

        result = _filter_by_curve_points(candidates, circle_center, circle_radius)

        assert len(result) == 0

    def test_profile_only_construction_falls_back_to_centroid(self):
        circle_center = make_point(0.0, 0.0, 0.0)
        circle_radius = 1.0

        circle_center_point = make_sketch_point(0.0, 0.0)
        profile = make_profile(area=1.0, centroid_x=0.0, centroid_y=0.0)
        loop = MagicMock()
        loop.profileCurves = [make_sketch_circle(circle_center_point, is_construction=True)]
        profile.profileLoops = [loop]

        candidates = [(profile, 1.0, 0.0)]

        result = _filter_by_curve_points(candidates, circle_center, circle_radius)

        assert len(result) == 1
        assert result[0][0] == profile

    def test_unsupported_sketch_entity_type_is_accepted(self):
        circle_center = make_point(0.0, 0.0, 0.0)
        circle_radius = 1.0

        class UnknownSketchEntity:
            pass

        sketch_entity = UnknownSketchEntity()
        sketch_entity.isConstruction = False
        sketch_entity.isReference = False
        profile_curve = MagicMock()
        profile_curve.sketchEntity = sketch_entity

        profile = make_profile(area=1.0, centroid_x=0.0, centroid_y=0.0)
        loop = MagicMock()
        loop.profileCurves = [profile_curve]
        profile.profileLoops = [loop]

        candidates = [(profile, 1.0, 0.0)]

        result = _filter_by_curve_points(candidates, circle_center, circle_radius)

        assert len(result) == 1
        assert result[0][0] == profile

    def test_error_in_curve_iteration_falls_back_to_centroid(self):
        circle_center = make_point(0.0, 0.0, 0.0)
        circle_radius = 1.0

        profile = make_profile(area=1.0, centroid_x=0.0, centroid_y=0.0)
        bad_loop = MagicMock()
        bad_loop.profileCurves = PropertyMock(side_effect=Exception('bad curve list'))
        profile.profileLoops = [bad_loop]

        candidates = [(profile, 1.0, 0.0)]

        result = _filter_by_curve_points(candidates, circle_center, circle_radius)

        assert len(result) == 1
        assert result[0][0] == profile


class TestFilterByBoundingBox:
    """Test _filter_by_bounding_box function."""

    def test_bbox_within_circle_bounds(self):
        """Bbox entirely within circle bounds should be included."""
        circle_center = make_point(0.0, 0.0, 0.0)
        circle_radius = 10.0

        # Margin: circle_radius * 1.0 = 10.0
        # Bounds: [center ± 2*radius] = [-20, 20]
        profile = make_profile(
            area=10.0,
            bbox_min_x=-5.0, bbox_min_y=-5.0,
            bbox_max_x=5.0, bbox_max_y=5.0
        )
        candidates = [(profile, 10.0, 1.0)]

        result = _filter_by_bounding_box(candidates, circle_center, circle_radius)

        assert len(result) == 1

    def test_bbox_outside_left_boundary(self):
        """Bbox extending past left boundary should be excluded."""
        circle_center = make_point(0.0, 0.0, 0.0)
        circle_radius = 10.0

        # Min bound: center.x - 2*radius = -20.0
        profile = make_profile(
            area=10.0,
            bbox_min_x=-21.0, bbox_min_y=-5.0,
            bbox_max_x=5.0, bbox_max_y=5.0
        )
        candidates = [(profile, 10.0, 1.0)]

        result = _filter_by_bounding_box(candidates, circle_center, circle_radius)

        assert len(result) == 0

    def test_bbox_outside_right_boundary(self):
        """Bbox extending past right boundary should be excluded."""
        circle_center = make_point(0.0, 0.0, 0.0)
        circle_radius = 10.0

        # Max bound: center.x + 2*radius = 20.0
        profile = make_profile(
            area=10.0,
            bbox_min_x=-5.0, bbox_min_y=-5.0,
            bbox_max_x=21.0, bbox_max_y=5.0
        )
        candidates = [(profile, 10.0, 1.0)]

        result = _filter_by_bounding_box(candidates, circle_center, circle_radius)

        assert len(result) == 0

    def test_bbox_outside_top_boundary(self):
        """Bbox extending past top boundary should be excluded."""
        circle_center = make_point(0.0, 0.0, 0.0)
        circle_radius = 10.0

        profile = make_profile(
            area=10.0,
            bbox_min_x=-5.0, bbox_min_y=-5.0,
            bbox_max_x=5.0, bbox_max_y=21.0
        )
        candidates = [(profile, 10.0, 1.0)]

        result = _filter_by_bounding_box(candidates, circle_center, circle_radius)

        assert len(result) == 0


class TestAccumulateProfiles:
    """Test _accumulate_profiles function."""

    def test_bbox_outside_left_boundary(self):
        """Bbox extending past left boundary should be excluded."""
        circle_center = make_point(0.0, 0.0, 0.0)
        circle_radius = 10.0

        # Min bound: center.x - 2*radius = -20.0
        profile = make_profile(
            area=10.0,
            bbox_min_x=-21.0, bbox_min_y=-5.0,
            bbox_max_x=5.0, bbox_max_y=5.0
        )
        candidates = [(profile, 10.0, 1.0)]

        result = _filter_by_bounding_box(candidates, circle_center, circle_radius)

        assert len(result) == 0

    def test_bbox_outside_right_boundary(self):
        """Bbox extending past right boundary should be excluded."""
        circle_center = make_point(0.0, 0.0, 0.0)
        circle_radius = 10.0

        # Max bound: center.x + 2*radius = 20.0
        profile = make_profile(
            area=10.0,
            bbox_min_x=-5.0, bbox_min_y=-5.0,
            bbox_max_x=21.0, bbox_max_y=5.0
        )
        candidates = [(profile, 10.0, 1.0)]

        result = _filter_by_bounding_box(candidates, circle_center, circle_radius)

        assert len(result) == 0

    def test_bbox_outside_top_boundary(self):
        """Bbox extending past top boundary should be excluded."""
        circle_center = make_point(0.0, 0.0, 0.0)
        circle_radius = 10.0

        profile = make_profile(
            area=10.0,
            bbox_min_x=-5.0, bbox_min_y=-5.0,
            bbox_max_x=5.0, bbox_max_y=21.0
        )
        candidates = [(profile, 10.0, 1.0)]

        result = _filter_by_bounding_box(candidates, circle_center, circle_radius)

        assert len(result) == 0


class TestAccumulateProfiles:
    """Test _accumulate_profiles function."""

    def test_single_profile_exact_match(self):
        """Single profile with exact area match should be selected."""
        target_area = 10.0
        profile = make_profile(area=10.0)
        candidates = [(profile, 10.0, 1.0)]

        profiles, difference = _accumulate_profiles(candidates, target_area)

        assert len(profiles) == 1
        assert profiles[0] == profile
        assert difference == pytest.approx(0.0, abs=1e-9)

    def test_two_profiles_sum_to_target(self):
        """Two profiles summing to target should be selected."""
        target_area = 10.0
        profile1 = make_profile(area=4.0)
        profile2 = make_profile(area=6.0)
        candidates = [
            (profile1, 4.0, 1.0),
            (profile2, 6.0, 1.0)
        ]

        profiles, difference = _accumulate_profiles(candidates, target_area)

        assert len(profiles) == 2
        assert difference == pytest.approx(0.0, abs=1e-9)

    def test_no_perfect_match(self):
        """Returns best combination even if not perfect match."""
        target_area = 10.0
        profile1 = make_profile(area=3.5)
        profile2 = make_profile(area=3.7)
        candidates = [
            (profile1, 3.5, 1.0),
            (profile2, 3.7, 1.0)
        ]

        profiles, difference = _accumulate_profiles(candidates, target_area)

        # Best combination is both: 3.5 + 3.7 = 7.2, diff = 2.8
        assert len(profiles) == 2
        assert difference == pytest.approx(2.8, abs=1e-9)

    def test_early_exit_on_very_close_match(self):
        """Should exit early if difference <= target * 0.00003."""
        target_area = 100.0
        # Threshold: 100.0 * 0.00003 = 0.003
        profile = make_profile(area=100.001)
        candidates = [(profile, 100.001, 1.0)]

        profiles, difference = _accumulate_profiles(candidates, target_area)

        assert len(profiles) == 1
        assert difference <= target_area * 0.00003

    def test_empty_candidates(self):
        """Empty candidates should return None and inf."""
        target_area = 10.0
        candidates = []

        profiles, difference = _accumulate_profiles(candidates, target_area)

        assert profiles is None
        assert difference == pytest.approx(float('inf'))

    def test_max_15_profiles_limit(self):
        """Should not exceed 15 profiles in a combination."""
        target_area = 15.0
        # Create 20 profiles with area 1.0 each
        candidates = [
            (make_profile(area=1.0), 1.0, float(i))
            for i in range(20)
        ]

        profiles, difference = _accumulate_profiles(candidates, target_area)

        # Should select at most 15 profiles
        assert len(profiles) <= 15

    def test_sorts_by_area_descending(self):
        """Should consider profiles in descending area order."""
        target_area = 10.0
        # Create profiles in increasing order
        profile1 = make_profile(area=2.0)
        profile2 = make_profile(area=4.0)
        profile3 = make_profile(area=6.0)

        candidates = [
            (profile1, 2.0, 1.0),
            (profile2, 4.0, 1.0),
            (profile3, 6.0, 1.0)
        ]

        profiles, difference = _accumulate_profiles(candidates, target_area)

        # Best match: 6.0 + 4.0 = 10.0 (exact)
        assert len(profiles) == 2
        assert profile2 in profiles
        assert profile3 in profiles
