"""
Cutting the first hole reshapes the face the user's sketch sits on, and Fusion then
refuses to create another sketch on it:

    RuntimeError: 3 : referencePlane is a BRefFace -
    need to roll timeline back before sketch

Acquiring the plane inside the cutting loop therefore cut the first hole and failed
every point after it, and rolling the timeline back could not help -- the add-in
consumed the face again on its own first cut. All the sketch work now happens before
anything cuts.
"""

from unittest.mock import MagicMock

import pytest

import adsk
import tm_config
import tm_execute
from tm_execute import CommandExecuteHandler, summarise_failures


M3_GRIP = (3.2, 7, 0.28, 1.5, 2.05, 3)
M3_STANDARD = (4.4, 5.7, 1.6)

BREF_FACE_ERROR = ('3 : referencePlane is a BRefFace - '
                   'need to roll timeline back before sketch')


class Recorder:
    """Records the order of sketch creation and cutting, and models the face dying.

    Fusion invalidates a sketch's referencePlane as soon as a feature reshapes the
    face it is on, so `cuts` flipping to 1 is what kills it.
    """

    def __init__(self, face_already_gone=False, coplanar_faces=()):
        self.calls = []
        self.cuts = 0
        self.face_already_gone = face_already_gone
        self.coplanar_faces = coplanar_faces

    @property
    def face_is_available(self):
        return not self.face_already_gone and self.cuts == 0

    def new_sketch(self, _face):
        self.calls.append('sketch')
        return MagicMock()

    def add_extrude(self, _input):
        self.calls.append('cut')
        self.cuts += 1
        return MagicMock()

    @property
    def sketches_made(self):
        return self.calls.count('sketch')

    @property
    def cuts_made(self):
        return self.calls.count('cut')


def build_args(recorder, insert_name, point_count):
    """One sketch, several points on it - the normal way this add-in is used."""
    body = MagicMock()
    body.name = 'Body1'
    # What the coplanar-face fallback has to work with
    body.faces = list(recorder.coplanar_faces)
    component = body.parentComponent
    component.parentDesign.timeline.markerPosition = 3
    component.sketches.addWithoutEdges = recorder.new_sketch
    component.features.extrudeFeatures.add = recorder.add_extrude

    # All the points share one sketch, so they share its plane
    parent_sketch = MagicMock()
    parent_sketch.name = 'Sketch3'

    def reference_plane(_self):
        recorder.calls.append('plane')
        if not recorder.face_is_available:
            raise RuntimeError(BREF_FACE_ERROR)
        return MagicMock()

    type(parent_sketch).referencePlane = property(reference_plane)

    points = []
    for _ in range(point_count):
        point = MagicMock()
        point.parentSketch = parent_sketch
        points.append(point)

    def selection_input(entities):
        sel = MagicMock()
        sel.selectionCount = len(entities)
        sel.selection = lambda i: MagicMock(entity=entities[i])
        return sel

    def plain(**attrs):
        m = MagicMock()
        for k, v in attrs.items():
            setattr(m, k, v)
        return m

    item = MagicMock()
    item.name = insert_name
    inputs = {
        'bodySelect': selection_input([body]),
        'pointSelect': selection_input(points),
        'insertSize': plain(selectedItem=item),
        'holeBlind': plain(value=True),
        'holeThrough': plain(value=False),
        'addChamfer': plain(value=False),
        'addBottomRadius': plain(value=False),
        'exportDebug': None,
    }

    args = MagicMock()
    args.command.commandInputs.itemById = lambda key: inputs.get(key)
    return args


@pytest.fixture(autouse=True)
def stub_fusion(monkeypatch):
    """Stub what needs a live document, and keep config.ini out of it."""
    monkeypatch.setattr(adsk.core.ValueInput, 'createByReal', lambda v: v, raising=False)
    for name in ('save_last_selected_insert', 'save_checkbox_states',
                 'save_settings', 'save_grip_ridge_insert'):
        monkeypatch.setattr(tm_config, name, lambda *a, **k: None)
    monkeypatch.setattr(tm_execute, 'create_grip_ridge_sketch', lambda *a, **k: MagicMock())
    monkeypatch.setattr(tm_execute, 'findProfileForCircle', lambda *a, **k: MagicMock())
    monkeypatch.setattr(tm_execute, 'findExtrudeDirectionFromSketch', lambda *a, **k: 'positive')
    monkeypatch.setattr(tm_execute, 'findDistanceThroughBody', lambda *a, **k: 5.0)
    monkeypatch.setattr(tm_execute, 'getGripRidgeChamferEdges', lambda *a, **k: None)
    monkeypatch.setattr(tm_execute, 'findChamferEdge', lambda *a, **k: None)
    monkeypatch.setattr(tm_execute, 'addBottomRadiusToBlindHole', lambda *a, **k: None)

    import tm_state
    monkeypatch.setitem(tm_state.GRIP_RIDGE_INSERTS, 'M3 Grip', M3_GRIP)
    monkeypatch.setitem(tm_state.INSERT_SPECS, 'M3 x 5.7mm (standard)', M3_STANDARD)
    monkeypatch.setitem(tm_state.CONFIG, 'show_success_message', False)
    monkeypatch.setitem(tm_state.CONFIG, 'blind_hole_extra_depth', 1.0)
    monkeypatch.setitem(tm_state.CONFIG, 'chamfer_size', 0.5)


@pytest.mark.parametrize('insert_name', ['M3 x 5.7mm (standard)', 'M3 Grip'])
class TestFaceSurvivesTheRun:

    def test_every_point_gets_a_hole(self, insert_name):
        """The bug: point 1 was cut, then the face died and 2 and 3 were skipped."""
        rec = Recorder()

        CommandExecuteHandler().notify(build_args(rec, insert_name, 3))

        assert rec.cuts_made == 3, 'a hole per selected point'

    def test_all_sketches_are_made_before_any_cutting(self, insert_name):
        """The ordering is the fix: nothing may cut until every sketch exists."""
        rec = Recorder()

        CommandExecuteHandler().notify(build_args(rec, insert_name, 3))

        assert rec.calls == ['plane', 'sketch'] * 3 + ['cut'] * 3

    def test_no_plane_is_read_after_the_first_cut(self, insert_name):
        """The invariant. Reading a plane after a cut is the bug: by then the cut
        has reshaped the face and Fusion will not resolve it."""
        rec = Recorder()

        CommandExecuteHandler().notify(build_args(rec, insert_name, 3))

        first_cut = rec.calls.index('cut')
        assert 'plane' not in rec.calls[first_cut:], (
            f'plane read after cutting started: {rec.calls}')


class TestFaceAlreadyGone:
    """referencePlane refuses AND the body has no face in the sketch's plane, so
    there is genuinely nothing left to sketch on."""

    def test_no_holes_and_one_grouped_explanation(self):
        rec = Recorder(face_already_gone=True)
        ui = MagicMock()
        import tm_state
        tm_state._ui = ui
        try:
            CommandExecuteHandler().notify(build_args(rec, 'M3 Grip', 3))
        finally:
            tm_state._ui = None

        assert rec.cuts_made == 0
        assert rec.sketches_made == 0
        assert rec.calls == ['plane'] * 3, 'tried each point, made nothing'

        said = ui.messageBox.call_args[0][0]
        # One paragraph naming all three points, not the same one three times
        assert said.count('Sketch3') == 1, 'the reason is shared, so say it once'
        assert 'Points 1, 2, 3' in said
        assert 'construction plane' in said


def a_coplanar_face():
    """A planar face of the body in the sketch's plane, which is all the temp sketch
    needs. findCoplanarFace is unit-tested in test_coplanar_face.py; here it is
    stubbed so this file stays about the run surviving."""
    return MagicMock()


class TestReferencePlaneAlwaysRefuses:
    """What the user actually hit: Fusion refuses the historical face from the very
    first point, with nothing of ours having touched the model yet. Rolling the
    timeline back does not help, so the run has to stop needing that face."""

    @pytest.fixture(autouse=True)
    def coplanar_face_found(self, monkeypatch):
        monkeypatch.setattr(tm_execute, 'findCoplanarFace',
                            lambda *a, **k: a_coplanar_face())

    @pytest.mark.parametrize('insert_name', ['M3 x 5.7mm (standard)', 'M3 Grip'])
    def test_all_holes_are_still_cut(self, insert_name):
        rec = Recorder(face_already_gone=True)

        CommandExecuteHandler().notify(build_args(rec, insert_name, 3))

        assert rec.cuts_made == 3, 'the fallback should carry the whole run'

    def test_nothing_is_reported_as_failed(self):
        rec = Recorder(face_already_gone=True)
        ui = MagicMock()
        import tm_state
        tm_state._ui = ui
        monkeyed = tm_state.CONFIG['show_success_message']
        tm_state.CONFIG['show_success_message'] = True
        try:
            CommandExecuteHandler().notify(build_args(rec, 'M3 Grip', 3))
        finally:
            tm_state.CONFIG['show_success_message'] = monkeyed
            tm_state._ui = None

        said = ui.messageBox.call_args[0][0]
        assert 'failed' not in said, said
        assert 'Successfully created 3' in said

    def test_sketches_still_all_precede_the_cutting(self):
        """The fallback must not reintroduce interleaving."""
        rec = Recorder(face_already_gone=True)

        CommandExecuteHandler().notify(build_args(rec, 'M3 Grip', 3))

        first_cut = rec.calls.index('cut')
        assert 'sketch' not in rec.calls[first_cut:]


class TestSummariseFailures:

    def test_one_point_reads_singular(self):
        assert summarise_failures([(2, 'nope')]) == 'Point 2: nope'

    def test_a_shared_reason_is_said_once(self):
        out = summarise_failures([(1, 'same'), (2, 'same'), (5, 'same')])
        assert out == 'Points 1, 2, 5: same'

    def test_different_reasons_stay_separate_in_order(self):
        out = summarise_failures([(1, 'first'), (2, 'second'), (3, 'first')])
        assert out == 'Points 1, 3: first\nPoint 2: second'

    def test_no_failures_is_empty(self):
        assert summarise_failures([]) == ''
