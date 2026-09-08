"""
Tests for the Restore Defaults controls in the Settings and Grip Ridge groups.

They act like buttons: ticking one resets that group's inputs immediately and
clears its own tick. Nothing reaches config.ini until OK, so Cancel undoes it.
"""

from unittest.mock import MagicMock

import pytest

import tm_state
import tm_ui
from tm_config import (
    GRIP_RIDGE_INPUTS,
    SETTINGS_INPUTS,
    default_grip_spec,
    get_default_grip_ridge_inserts,
    load_config,
)


M3_GRIP_DEFAULT = get_default_grip_ridge_inserts()['M3 Grip']


class FakeInputs:
    """Command inputs that remember the values written to them."""

    def __init__(self, values, selected_insert='M3 Grip'):
        self.values = dict(values)
        self._selected = selected_insert

    def itemById(self, input_id):
        if input_id == 'insertSize':
            # MagicMock(name=...) names the mock, so set .name afterwards
            item = MagicMock()
            item.name = self._selected
            return MagicMock(selectedItem=item)
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


def change(inputs, input_id):
    """Fire InputChangedHandler for one input."""
    args = MagicMock()
    args.inputs = inputs
    args.input = inputs.itemById(input_id)
    tm_ui.InputChangedHandler().notify(args)


@pytest.fixture(autouse=True)
def quiet_info_text(monkeypatch):
    """updateInfoText needs the whole dialog; not what these tests are about."""
    monkeypatch.setattr(tm_ui, 'updateInfoText', lambda inputs: None)


class TestRestoreSettings:

    def edited(self):
        """Every setting moved off its default."""
        values = {'setRestoreDefaults': False}
        for input_id, (key, _section) in SETTINGS_INPUTS.items():
            default = tm_state.DEFAULT_CONFIG[key]
            values[input_id] = (not default) if isinstance(default, bool) else default + 1.0
        return FakeInputs(values)

    def test_resets_every_setting_to_its_default(self):
        inputs = self.edited()
        inputs.values['setRestoreDefaults'] = True

        change(inputs, 'setRestoreDefaults')

        for input_id, (key, _section) in SETTINGS_INPUTS.items():
            assert inputs.values[input_id] == tm_state.DEFAULT_CONFIG[key], input_id

    def test_clears_its_own_tick(self):
        """So it reads as a button rather than a setting that stays on."""
        inputs = self.edited()
        inputs.values['setRestoreDefaults'] = True

        change(inputs, 'setRestoreDefaults')

        assert inputs.values['setRestoreDefaults'] is False

    def test_unticking_changes_nothing(self):
        """The untick the handler itself causes must not re-run the reset."""
        inputs = self.edited()
        before = dict(inputs.values)

        change(inputs, 'setRestoreDefaults')

        assert inputs.values == before


class TestRestoreGripRidge:

    def edited(self, selected_insert='M3 Grip'):
        values = {'gripRestoreDefaults': False}
        values.update(dict(zip(GRIP_RIDGE_INPUTS, (9.9, 9.9, 0.9, 9.9, 9.9, 11))))
        return FakeInputs(values, selected_insert)

    def test_resets_the_selected_insert_to_its_shipped_spec(self):
        inputs = self.edited()
        inputs.values['gripRestoreDefaults'] = True

        change(inputs, 'gripRestoreDefaults')

        restored = tuple(inputs.values[input_id] for input_id in GRIP_RIDGE_INPUTS)
        assert restored == M3_GRIP_DEFAULT

    def test_restores_the_insert_that_is_selected(self):
        """Not whatever happened to be first in the table."""
        inputs = self.edited(selected_insert='M8 Grip')
        inputs.values['gripRestoreDefaults'] = True

        change(inputs, 'gripRestoreDefaults')

        restored = tuple(inputs.values[input_id] for input_id in GRIP_RIDGE_INPUTS)
        assert restored == get_default_grip_ridge_inserts()['M8 Grip']

    def test_clears_its_own_tick(self):
        inputs = self.edited()
        inputs.values['gripRestoreDefaults'] = True

        change(inputs, 'gripRestoreDefaults')

        assert inputs.values['gripRestoreDefaults'] is False

    def test_unticking_changes_nothing(self):
        inputs = self.edited()
        before = dict(inputs.values)

        change(inputs, 'gripRestoreDefaults')

        assert inputs.values == before


class TestDefaultGripSpec:

    def test_returns_the_shipped_spec(self):
        assert default_grip_spec('M3 Grip') == M3_GRIP_DEFAULT

    def test_falls_back_to_the_stored_row_for_a_user_added_insert(self, monkeypatch):
        """We ship no default for it, so its config.ini row is the best we have."""
        custom = (12.5, 16, 0.7, 4.5, 7.5, 6)
        monkeypatch.setitem(tm_state.GRIP_RIDGE_INSERTS, 'M12 Grip', custom)

        assert default_grip_spec('M12 Grip') == custom

    def test_unknown_insert_gives_nothing_to_restore(self, monkeypatch):
        monkeypatch.delitem(tm_state.GRIP_RIDGE_INSERTS, 'Nope Grip', raising=False)

        assert default_grip_spec('Nope Grip') is None

    def test_restore_is_a_no_op_when_there_is_no_default(self):
        """A missing spec must leave the inputs alone rather than crash."""
        inputs = FakeInputs(
            dict({'gripRestoreDefaults': True},
                 **dict(zip(GRIP_RIDGE_INPUTS, (9.9, 9.9, 0.9, 9.9, 9.9, 11)))),
            selected_insert='Nope Grip')

        change(inputs, 'gripRestoreDefaults')

        assert tuple(inputs.values[i] for i in GRIP_RIDGE_INPUTS) == (9.9, 9.9, 0.9, 9.9, 9.9, 11)
        assert inputs.values['gripRestoreDefaults'] is False


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
