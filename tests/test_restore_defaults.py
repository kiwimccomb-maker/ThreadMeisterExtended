"""
Tests for the Restore Defaults / Save / Restore User Saved buttons.

Each acts at once so the result is visible in the dialog, then clears itself so it
reads as a button. Only Save writes config.ini.

The handler reads the command's own inputs, not args.inputs: for an input inside a
group, args.inputs is that group's children, where the top-level ids do not exist.
Reading it raised AttributeError on itemById('insertSize').
"""

from unittest.mock import MagicMock

import pytest

import tm_config
import tm_state
import tm_ui
from tm_config import (
    GRIP_GLOBAL_INPUTS,
    GRIP_RIDGE_INPUTS,
    HEAT_INSERT_INPUTS,
    default_grip_spec,
    get_default_grip_ridge_inserts,
    load_config,
)


M3_GRIP_DEFAULT = get_default_grip_ridge_inserts()['M3 Grip']
EDITED_SPEC = (9.9, 9.9, 0.9, 9.9, 9.9, 11)


class FakeInputs:
    """Command inputs that remember the values written to them."""

    def __init__(self, values, selected_insert='M3 Grip'):
        self.values = dict(values)
        self._selected = selected_insert

    def _list_input(self, name):
        item = MagicMock()
        item.name = name          # MagicMock(name=...) names the mock instead
        return MagicMock(selectedItem=item)

    def itemById(self, input_id):
        if input_id == 'insertSize':
            return self._list_input(self._selected)
        if input_id == 'insertType':
            return self._list_input(
                tm_ui.INSERT_TYPE_GRIP if self._selected in tm_state.GRIP_RIDGE_INSERTS
                else tm_ui.INSERT_TYPE_HEAT)
        if input_id not in self.values:
            return None
        holder = self

        class _Input:
            id = input_id

            @property
            def value(self):
                return holder.values[input_id]

            @value.setter
            def value(self, new_value):
                holder.values[input_id] = new_value

        return _Input()


def press(inputs, input_id):
    """Fire InputChangedHandler for one input, the way Fusion does."""
    args = MagicMock()
    args.input = inputs.itemById(input_id)
    # The handler must reach the command's own inputs, not the group's children
    args.firingEvent.sender.commandInputs = inputs
    args.inputs = MagicMock(itemById=lambda _id: None)
    tm_ui.InputChangedHandler().notify(args)


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    """updateInfoText needs the whole dialog; saving must not touch config.ini."""
    monkeypatch.setattr(tm_ui, 'updateInfoText', lambda inputs: None)
    monkeypatch.setattr(tm_state, '_ui', MagicMock())
    saved = {}
    monkeypatch.setattr(tm_config, 'save_settings',
                        lambda values, *a, **k: saved.update({'settings': values}))
    monkeypatch.setattr(tm_config, 'save_grip_ridge_insert',
                        lambda name, spec, *a, **k: saved.update({'grip': (name, spec)}))
    monkeypatch.setattr(tm_config, 'save_checkbox_states', lambda *a, **k: None)
    return saved


def heat_inputs(edited=True):
    values = {'heatRestoreDefaults': False, 'heatSave': False, 'heatRestoreSaved': False,
              'addChamfer': False, 'addBottomRadius': True}
    for input_id, (key, _section) in HEAT_INSERT_INPUTS.items():
        values[input_id] = tm_state.DEFAULT_CONFIG[key] + (1.0 if edited else 0.0)
    return FakeInputs(values, selected_insert='M3 x 5.7mm (standard)')


def grip_inputs(edited=True):
    values = {'gripRestoreDefaults': False, 'gripSave': False, 'gripRestoreSaved': False}
    values.update(dict(zip(GRIP_RIDGE_INPUTS, EDITED_SPEC if edited else M3_GRIP_DEFAULT)))
    for input_id, (key, _section) in GRIP_GLOBAL_INPUTS.items():
        values[input_id] = tm_state.DEFAULT_CONFIG[key] + (1.0 if edited else 0.0)
    return FakeInputs(values)


class TestTheCrashIsGone:
    """itemById('insertSize') returned None because args.inputs was the group's
    children, so .selectedItem raised AttributeError."""

    @pytest.mark.parametrize('button', ['gripRestoreDefaults', 'gripSave',
                                        'gripRestoreSaved'])
    def test_pressing_a_grip_button_does_not_raise(self, button):
        inputs = grip_inputs()
        inputs.values[button] = True

        press(inputs, button)

        assert not tm_state._ui.messageBox.called, tm_state._ui.messageBox.call_args


class TestRestoreDefaults:

    def test_grip_resets_to_the_shipped_spec(self):
        inputs = grip_inputs()
        inputs.values['gripRestoreDefaults'] = True

        press(inputs, 'gripRestoreDefaults')

        assert tuple(inputs.values[i] for i in GRIP_RIDGE_INPUTS) == M3_GRIP_DEFAULT

    def test_grip_also_resets_the_chamfer_angle(self):
        """It moved into this group, so this button owns it."""
        inputs = grip_inputs()
        inputs.values['gripRestoreDefaults'] = True

        press(inputs, 'gripRestoreDefaults')

        assert inputs.values['setGripChamferAngle'] == tm_state.DEFAULT_CONFIG['grip_chamfer_angle']

    def test_grip_restores_the_size_that_is_selected(self):
        inputs = grip_inputs()
        inputs._selected = 'M8 Grip'
        inputs.values['gripRestoreDefaults'] = True

        press(inputs, 'gripRestoreDefaults')

        assert tuple(inputs.values[i] for i in GRIP_RIDGE_INPUTS) == \
            get_default_grip_ridge_inserts()['M8 Grip']

    def test_heat_resets_its_own_parameters(self):
        inputs = heat_inputs()
        inputs.values['heatRestoreDefaults'] = True

        press(inputs, 'heatRestoreDefaults')

        for input_id, (key, _section) in HEAT_INSERT_INPUTS.items():
            assert inputs.values[input_id] == tm_state.DEFAULT_CONFIG[key], input_id

    def test_heat_resets_the_chamfer_and_fillet_toggles(self):
        inputs = heat_inputs()
        inputs.values['heatRestoreDefaults'] = True

        press(inputs, 'heatRestoreDefaults')

        assert inputs.values['addChamfer'] == tm_state.DEFAULT_CONFIG['chamfer_enabled_default']
        assert inputs.values['addBottomRadius'] == \
            tm_state.DEFAULT_CONFIG['bottom_radius_enabled_default']

    def test_restoring_defaults_writes_nothing(self, isolate):
        inputs = grip_inputs()
        inputs.values['gripRestoreDefaults'] = True

        press(inputs, 'gripRestoreDefaults')

        assert isolate == {}, 'config.ini is only written by Save'


class TestSave:

    def test_grip_save_writes_the_edited_spec(self, isolate, monkeypatch):
        monkeypatch.setitem(tm_state.GRIP_RIDGE_INSERTS, 'M3 Grip', M3_GRIP_DEFAULT)
        inputs = grip_inputs()
        inputs.values['gripSave'] = True

        press(inputs, 'gripSave')

        assert isolate['grip'] == ('M3 Grip', EDITED_SPEC)

    def test_grip_save_updates_what_the_dialog_reopens_with(self, monkeypatch):
        monkeypatch.setitem(tm_state.GRIP_RIDGE_INSERTS, 'M3 Grip', M3_GRIP_DEFAULT)
        inputs = grip_inputs()
        inputs.values['gripSave'] = True

        press(inputs, 'gripSave')

        assert tm_state.GRIP_RIDGE_INSERTS['M3 Grip'] == EDITED_SPEC

    def test_heat_save_writes_the_settings(self, isolate):
        inputs = heat_inputs()
        inputs.values['heatSave'] = True

        press(inputs, 'heatSave')

        assert 'settings' in isolate


class TestRestoreUserSaved:

    def test_grip_goes_back_to_the_saved_row(self, monkeypatch):
        saved = (4.0, 9.0, 0.4, 2.0, 2.5, 5)
        monkeypatch.setattr(tm_config, 'saved_grip_spec', lambda name, *a: saved)
        monkeypatch.setattr(tm_config, 'saved_settings',
                            lambda *a: dict(tm_state.DEFAULT_CONFIG))
        inputs = grip_inputs()
        inputs.values['gripRestoreSaved'] = True

        press(inputs, 'gripRestoreSaved')

        assert tuple(inputs.values[i] for i in GRIP_RIDGE_INPUTS) == saved

    def test_heat_goes_back_to_the_saved_settings(self, monkeypatch):
        stored = {key: 2.5 for _id, (key, _s) in HEAT_INSERT_INPUTS.items()}
        monkeypatch.setattr(tm_config, 'saved_settings', lambda *a: stored)
        inputs = heat_inputs()
        inputs.values['heatRestoreSaved'] = True

        press(inputs, 'heatRestoreSaved')

        for input_id in HEAT_INSERT_INPUTS:
            assert inputs.values[input_id] == 2.5

    def test_an_insert_with_no_saved_row_is_left_alone(self, monkeypatch):
        monkeypatch.setattr(tm_config, 'saved_grip_spec', lambda name, *a: None)
        monkeypatch.setattr(tm_config, 'saved_settings',
                            lambda *a: dict(tm_state.DEFAULT_CONFIG))
        inputs = grip_inputs()
        inputs.values['gripRestoreSaved'] = True

        press(inputs, 'gripRestoreSaved')

        assert tuple(inputs.values[i] for i in GRIP_RIDGE_INPUTS) == EDITED_SPEC


class TestButtonsClearThemselves:

    @pytest.mark.parametrize('button', ['gripRestoreDefaults', 'gripSave',
                                        'gripRestoreSaved'])
    def test_pressed_button_resets(self, button):
        inputs = grip_inputs()
        inputs.values[button] = True

        press(inputs, button)

        assert inputs.values[button] is False

    def test_an_unpressed_button_does_nothing(self):
        inputs = grip_inputs()
        before = dict(inputs.values)

        press(inputs, 'gripRestoreDefaults')

        assert inputs.values == before


class TestDefaultGripSpec:

    def test_returns_the_shipped_spec(self):
        assert default_grip_spec('M3 Grip') == M3_GRIP_DEFAULT

    def test_falls_back_to_the_stored_row_for_a_user_added_insert(self, monkeypatch):
        custom = (12.5, 16, 0.7, 4.5, 7.5, 6)
        monkeypatch.setitem(tm_state.GRIP_RIDGE_INSERTS, 'M12 Grip', custom)

        assert default_grip_spec('M12 Grip') == custom

    def test_unknown_insert_gives_nothing_to_restore(self, monkeypatch):
        monkeypatch.delitem(tm_state.GRIP_RIDGE_INSERTS, 'Nope Grip', raising=False)

        assert default_grip_spec('Nope Grip') is None


class TestDefaultsAreOneSource:
    """DEFAULT_CONFIG has to be what load_config actually falls back to."""

    def test_empty_config_loads_the_defaults(self, tmp_path):
        empty = tmp_path / 'empty.ini'
        empty.write_text('[Settings]\n', encoding='utf-8')

        _specs, config = load_config(str(empty))

        for key, expected in tm_state.DEFAULT_CONFIG.items():
            assert config[key] == expected, f'{key} did not fall back to its default'

    def test_out_of_range_values_reset_to_the_defaults(self, tmp_path):
        bad = tmp_path / 'bad.ini'
        bad.write_text(
            '[Settings]\n'
            'chamfer_size = 99\n'
            'blind_hole_extra_depth = -5\n'
            'bottom_radius_size = 99\n'
            'grip_chamfer_angle = 200\n',
            encoding='utf-8')

        _specs, config = load_config(str(bad))

        for key in ('chamfer_size', 'blind_hole_extra_depth',
                    'bottom_radius_size', 'grip_chamfer_angle'):
            assert config[key] == tm_state.DEFAULT_CONFIG[key], key
