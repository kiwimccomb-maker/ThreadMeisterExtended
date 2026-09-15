"""
Integration test for the hole depth CommandExecuteHandler actually extrudes.

The depth arrives in mm from the spec (or the spinner) and Fusion wants cm, and
the conversion happens inside the per-point loop. Getting that wrong is invisible
on a single point and only shows up from the second hole onwards, so this drives
the real handler over two points and checks both extrudes.
"""

import sys
from unittest.mock import MagicMock

import pytest

import adsk
import tm_state
import tm_config
import tm_execute
from tm_execute import CommandExecuteHandler


M3_GRIP = (3.2, 7, 0.28, 1.5, 2.05, 3)   # clearance, depth mm, chamfer, ridge dia, arc dist, count
M3_STANDARD = (4.4, 5.7, 1.6)            # hole dia, insert length mm, min wall


def make_input(**attrs):
    inp = MagicMock()
    for k, v in attrs.items():
        setattr(inp, k, v)
    return inp


def make_selection_input(entities):
    sel = MagicMock()
    sel.selectionCount = len(entities)
    sel.selection = lambda i: MagicMock(entity=entities[i])
    return sel


def build_args(insert_name, point_count, is_blind=True, chamfer=False,
               spinner_value_mm=None):
    """Assemble the command inputs the handler reads."""
    tm_state.CONFIG['hole_type_blind'] = is_blind
    body = MagicMock()
    component = body.parentComponent
    design = component.parentDesign
    design.timeline.markerPosition = 3

    points = []
    for _ in range(point_count):
        point = MagicMock()
        # project() returns a collection; item(0) is the projected point
        point.parentSketch.referencePlane = MagicMock()
        points.append(point)

    spinner = None
    if spinner_value_mm is not None:
        spinner = make_input(isVisible=True, value=spinner_value_mm)

    inputs = {
        'bodySelect': make_selection_input([body]),
        'pointSelect': make_selection_input(points),
        'insertSize': make_input(selectedItem=make_input(name=insert_name)),
        # Hole type is read from CONFIG, not from an input: its row lives in a
        # table, whose contents itemById does not reach.

        'addChamfer': make_input(value=chamfer),
        'addBottomRadius': make_input(value=False),
        'exportDebug': None,
        'gripEdgeDepth': spinner,
    }

    args = MagicMock()
    args.command.commandInputs.itemById = lambda key: inputs.get(key)
    return args, component


@pytest.fixture
def captured_depths(monkeypatch):
    """Run the handler with the Fusion calls stubbed, collecting extrude depths."""
    depths = []

    monkeypatch.setattr(adsk.core.ValueInput, 'createByReal',
                        lambda value: depths.append(value) or value, raising=False)
    # Config writes would touch the real config.ini
    monkeypatch.setattr(tm_config, 'save_last_selected_insert', lambda *a, **k: None)
    monkeypatch.setattr(tm_config, 'save_checkbox_states', lambda *a, **k: None)
    monkeypatch.setattr(tm_config, 'save_settings', lambda *a, **k: None)
    monkeypatch.setattr(tm_config, 'save_grip_ridge_insert', lambda *a, **k: None)
    # Geometry that needs a live Fusion document
    monkeypatch.setattr(tm_execute, 'create_grip_ridge_sketch', lambda *a, **k: MagicMock())
    monkeypatch.setattr(tm_execute, 'findProfileForCircle', lambda *a, **k: MagicMock())
    monkeypatch.setattr(tm_execute, 'findExtrudeDirectionFromSketch', lambda *a, **k: 'positive')
    monkeypatch.setattr(tm_execute, 'findDistanceThroughBody', lambda *a, **k: 5.0)
    monkeypatch.setattr(tm_execute, 'getGripRidgeChamferEdges', lambda *a, **k: None)
    monkeypatch.setattr(tm_execute, 'findChamferEdge', lambda *a, **k: None)
    monkeypatch.setattr(tm_execute, 'addBottomRadiusToBlindHole', lambda *a, **k: None)

    monkeypatch.setitem(tm_state.GRIP_RIDGE_INSERTS, 'M3 Grip', M3_GRIP)
    monkeypatch.setitem(tm_state.INSERT_SPECS, 'M3 x 5.7mm (standard)', M3_STANDARD)
    monkeypatch.setitem(tm_state.CONFIG, 'show_success_message', False)
    monkeypatch.setitem(tm_state.CONFIG, 'blind_hole_extra_depth', 1.0)
    monkeypatch.setitem(tm_state.CONFIG, 'chamfer_size', 0.5)

    return depths


class TestGripRidgeDepth:
    """M3 Grip is a 7mm hole, which Fusion wants as 0.7 cm."""

    def test_single_point(self, captured_depths):
        args, _ = build_args('M3 Grip', point_count=1)

        CommandExecuteHandler().notify(args)

        assert captured_depths == [pytest.approx(0.7)]

    def test_every_point_gets_the_same_depth(self, captured_depths):
        """Regression: the loop used to write the cm result back over the mm
        spec value, so points 2+ were cut 10x too shallow."""
        args, _ = build_args('M3 Grip', point_count=3)

        CommandExecuteHandler().notify(args)

        assert captured_depths == [pytest.approx(0.7)] * 3

    def test_spinner_override_applies_to_every_point(self, captured_depths):
        """A 12 mm override on the depth spinner, on all 3 holes."""
        args, _ = build_args('M3 Grip', point_count=3, spinner_value_mm=12.0)

        CommandExecuteHandler().notify(args)

        assert captured_depths == [pytest.approx(1.2)] * 3


class TestStandardInsertDepth:
    """Standard inserts: insert length + extra depth (+ chamfer when enabled)."""

    def test_depth_without_chamfer(self, captured_depths):
        # 5.7 + 1.0 = 6.7 mm
        args, _ = build_args('M3 x 5.7mm (standard)', point_count=2)

        CommandExecuteHandler().notify(args)

        assert captured_depths == [pytest.approx(0.67)] * 2

    def test_chamfer_adds_to_depth(self, captured_depths):
        # 5.7 + 1.0 + 0.5 = 7.2 mm
        args, _ = build_args('M3 x 5.7mm (standard)', point_count=2, chamfer=True)

        CommandExecuteHandler().notify(args)

        assert captured_depths == [pytest.approx(0.72)] * 2
