"""
Fusion will not always resolve the face a sketch was drawn on: it wants the timeline
rolled back to the sketch first, and reports

    RuntimeError: 3 : referencePlane is a BRefFace -
    need to roll timeline back before sketch

even with nothing after that sketch. The temp sketch does not need the historical
face though - it needs a plane in the same place, and a face of the body lying in the
sketch's plane is exactly that, read off the body as it is now.
"""

import math
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import adsk
from tm_geometry import findCoplanarFace


def vec(x, y, z):
    return SimpleNamespace(x=x, y=y, z=z)


def point(x, y, z):
    p = SimpleNamespace(x=x, y=y, z=z)
    p.copy = lambda: point(p.x, p.y, p.z)
    p.transformBy = lambda _t: None
    return p


def plane_face(area, origin=(0.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0),
               surface_type='PlaneSurfaceType'):
    """A planar BRepFace at a given plane."""
    face = MagicMock()
    face.area = area
    face.geometry = SimpleNamespace(
        surfaceType=surface_type,
        origin=point(*origin),
        normal=vec(*normal))
    return face


def cylinder_face(area=99.0):
    """The wall of an existing hole - parallel test must not pick this."""
    return plane_face(area, surface_type='CylinderSurfaceType')


class FlatSketch:
    """A sketch in the world XY plane, at z = height."""

    def __init__(self, height=0.0):
        self.height = height
        self.transform = self

    def getAsCoordinateSystem(self):
        return (point(0.0, 0.0, self.height), vec(1, 0, 0), vec(0, 1, 0), vec(0, 0, 1))


@pytest.fixture(autouse=True)
def point3d_create(monkeypatch):
    """The function builds its 3D centre through the API."""
    sketch_height = {'z': 0.0}

    def create(x, y, z=0.0):
        p = point(x, y, z)
        # transformBy applies the sketch transform; for these flat sketches that is
        # just a lift to the sketch's height.
        p.transformBy = lambda _t: setattr(p, 'z', sketch_height['z'])
        return p

    monkeypatch.setattr(adsk.core.Point3D, 'create', create, raising=False)
    return sketch_height


def body_with(*faces):
    b = MagicMock()
    b.faces = list(faces)
    return b


class TestFindCoplanarFace:

    def test_picks_the_face_in_the_sketch_plane(self, point3d_create):
        wanted = plane_face(area=50.0, origin=(0, 0, 0))
        body = body_with(wanted)

        got = findCoplanarFace(body, FlatSketch(), point(1.0, 1.0, 0.0))

        assert got is wanted

    def test_ignores_a_parallel_face_at_another_height(self, point3d_create):
        """A plate's underside is parallel to the sketch but a thickness away."""
        underside = plane_face(area=50.0, origin=(0, 0, -2.0))
        body = body_with(underside)

        assert findCoplanarFace(body, FlatSketch(), point(1.0, 1.0, 0.0)) is None

    def test_ignores_a_perpendicular_face(self, point3d_create):
        side = plane_face(area=50.0, origin=(0, 0, 0), normal=(1.0, 0.0, 0.0))
        body = body_with(side)

        assert findCoplanarFace(body, FlatSketch(), point(1.0, 1.0, 0.0)) is None

    def test_ignores_non_planar_faces(self, point3d_create):
        body = body_with(cylinder_face())

        assert findCoplanarFace(body, FlatSketch(), point(1.0, 1.0, 0.0)) is None

    def test_prefers_the_larger_coplanar_face(self, point3d_create):
        """Any coplanar face gives the same plane, so this is only a tie-break -
        but the face that was sketched on is usually the big one."""
        small = plane_face(area=1.0)
        large = plane_face(area=80.0)
        body = body_with(small, large)

        assert findCoplanarFace(body, FlatSketch(), point(0.0, 0.0, 0.0)) is large

    def test_accepts_an_upside_down_normal(self, point3d_create):
        """Coplanar is coplanar; which way the face points does not matter."""
        flipped = plane_face(area=50.0, normal=(0.0, 0.0, -1.0))
        body = body_with(flipped)

        assert findCoplanarFace(body, FlatSketch(), point(0.0, 0.0, 0.0)) is flipped

    def test_matches_a_sketch_that_is_not_at_the_origin(self, point3d_create):
        """A sketch on the top of a 2 cm plate."""
        point3d_create['z'] = 2.0
        top = plane_face(area=50.0, origin=(0, 0, 2.0))
        underside = plane_face(area=50.0, origin=(0, 0, 0.0))
        body = body_with(underside, top)

        assert findCoplanarFace(body, FlatSketch(height=2.0), point(1.0, 1.0, 0.0)) is top

    def test_no_faces_at_all_is_not_fatal(self, point3d_create):
        assert findCoplanarFace(body_with(), FlatSketch(), point(0.0, 0.0, 0.0)) is None

    def test_a_broken_body_is_not_fatal(self, point3d_create):
        """It is a fallback; it must never be the thing that raises."""
        broken = MagicMock()
        type(broken).faces = property(lambda self: (_ for _ in ()).throw(RuntimeError('gone')))

        assert findCoplanarFace(broken, FlatSketch(), point(0.0, 0.0, 0.0)) is None
