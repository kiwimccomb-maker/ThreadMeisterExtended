"""
Tests for the per-insert Grip Ridge parameters editable in the dialog.

These write back into [GripRidgeInserts], one row per insert, so the round trip
through config.ini and the geometry sanity check both matter.
"""

import io
from unittest.mock import MagicMock

import pytest

import tm_state
from tm_helpers import grip_ridge_warning
from tm_config import (
    GRIP_RIDGE_INPUTS,
    get_default_grip_ridge_inserts,
    load_config,
    read_grip_inputs,
    save_grip_ridge_insert,
)


M3_GRIP = (3.2, 7, 0.28, 1.5, 2.05, 3)


def read(path):
    return io.open(path, encoding='utf-8').read()


class TestGripRidgeWarning:
    """Guard rails for combinations that cannot produce a ridge."""

    def test_every_shipped_default_is_sound(self):
        """No insert we ship may trip the warning."""
        for name, (clearance, _depth, _chamfer,
                   ridge_dia, arc_distance, count) in get_default_grip_ridge_inserts().items():
            warning = grip_ridge_warning(clearance, ridge_dia, arc_distance, count)
            assert warning is None, f'{name}: {warning}'

    def test_ridges_too_far_out(self):
        """Ridge circle clears the bore wall entirely, so nothing protrudes."""
        warning = grip_ridge_warning(3.2, 1.5, 5.0, 3)

        assert warning is not None
        assert 'outside the bore' in warning

    def test_ridges_too_far_in(self):
        """Ridge circle sits wholly inside the bore, so there is no wall left."""
        warning = grip_ridge_warning(3.2, 1.5, 0.2, 3)

        assert warning is not None
        assert 'swallow' in warning

    def test_too_many_ridges_overlap(self):
        """Twelve M3-sized ridges run into each other."""
        warning = grip_ridge_warning(3.2, 1.5, 2.05, 12)

        assert warning is not None
        assert 'overlap' in warning

    def test_a_single_ridge_never_overlaps_itself(self):
        assert grip_ridge_warning(3.2, 1.5, 2.05, 1) is None


class TestReadGripInputs:
    """Reading the Grip Ridge group back as a spec tuple."""

    @pytest.fixture(autouse=True)
    def stored_spec(self, monkeypatch):
        monkeypatch.setitem(tm_state.GRIP_RIDGE_INSERTS, 'M3 Grip', M3_GRIP)

    def test_reads_every_input_in_spec_order(self):
        values = dict(zip(GRIP_RIDGE_INPUTS, [4.0, 9.0, 0.4, 2.0, 2.5, 5]))
        inputs = MagicMock()
        inputs.itemById = lambda key: (MagicMock(value=values[key])
                                       if key in values else None)

        assert read_grip_inputs(inputs, 'M3 Grip') == (4.0, 9.0, 0.4, 2.0, 2.5, 5)

    def test_falls_back_to_the_stored_spec(self):
        """The group is hidden for standard inserts and absent before it is built."""
        inputs = MagicMock()
        inputs.itemById = lambda key: None

        assert read_grip_inputs(inputs, 'M3 Grip') == M3_GRIP

    def test_partial_inputs_keep_the_rest_of_the_spec(self):
        inputs = MagicMock()
        inputs.itemById = lambda key: (MagicMock(value=9.0)
                                       if key == 'gripEdgeDepth' else None)

        assert read_grip_inputs(inputs, 'M3 Grip') == (3.2, 9.0, 0.28, 1.5, 2.05, 3)

    def test_ridge_count_is_an_integer(self):
        """A float count would be written to config.ini and rejected on load."""
        inputs = MagicMock()
        inputs.itemById = lambda key: (MagicMock(value=4.0)
                                       if key == 'gripCount' else None)

        assert read_grip_inputs(inputs, 'M3 Grip')[5] == 4
        assert isinstance(read_grip_inputs(inputs, 'M3 Grip')[5], int)


class TestSaveGripRidgeInsert:
    """Writing one [GripRidgeInserts] row."""

    def test_round_trips_through_load_config(self, config_file):
        save_grip_ridge_insert('M3 Grip', (4.0, 9.0, 0.4, 2.0, 2.5, 5), config_file)

        load_config(config_file)

        assert tm_state.GRIP_RIDGE_INSERTS['M3 Grip'] == (4.0, 9.0, 0.4, 2.0, 2.5, 5)

    def test_keeps_the_format_comment(self, config_file):
        save_grip_ridge_insert('M3 Grip', (4.0, 9.0, 0.4, 2.0, 2.5, 5), config_file)

        assert '# Format: clearance_dia, hole_depth' in read(config_file)

    def test_leaves_other_sections_alone(self, config_file):
        save_grip_ridge_insert('M3 Grip', (4.0, 9.0, 0.4, 2.0, 2.5, 5), config_file)

        text = read(config_file)
        assert 'M3 x 5.7mm (standard) = 4.4, 5.7, 1.6' in text
        assert 'chamfer_size = 0.5' in text

    def test_adds_an_insert_that_is_not_in_the_file(self, config_file):
        save_grip_ridge_insert('M12 Grip', (12.5, 16, 0.7, 4.5, 7.5, 6), config_file)

        specs, _config = load_config(config_file)

        assert tm_state.GRIP_RIDGE_INSERTS['M12 Grip'] == (12.5, 16, 0.7, 4.5, 7.5, 6)
        assert 'M3 Grip' in tm_state.GRIP_RIDGE_INSERTS


class TestGripRidgeGroup:
    """The dialog group and the spec tuple have to stay in step."""

    @pytest.fixture
    def built(self, monkeypatch, recording_inputs):
        import tm_ui
        monkeypatch.setitem(tm_state.GRIP_RIDGE_INSERTS, 'M3 Grip', M3_GRIP)
        tm_ui._addGripRidgeGroup(recording_inputs, 'M3 Grip')
        return recording_inputs

    def test_every_mapped_parameter_has_an_input(self, built):
        """A drifted id would silently fall back to the stored spec and never save."""
        created = set(built.spinners) | set(built.integers)

        # setGripChamferAngle is shown here too, but it is a global setting
        assert set(GRIP_RIDGE_INPUTS) <= created, (
            f'not built: {set(GRIP_RIDGE_INPUTS) - created}')

    def test_hole_depth_comes_first(self, built):
        """The one parameter that gets edited regularly is not buried."""
        assert built.order[0] == 'gripEdgeDepth'

    def test_the_shape_parameters_are_in_a_collapsed_sub_group(self, built):
        """Everything but the depth stays out of the way until asked for."""
        assert built.collapsed.get('gripShapeGroup') is True

    def test_every_parameter_has_a_tooltip(self, built):
        for input_id in GRIP_RIDGE_INPUTS:
            assert built.tooltips.get(input_id), f'{input_id} has no tooltip'

    def test_inputs_open_on_the_selected_insert_spec(self, built):
        opened = tuple(
            (built.spinners.get(input_id) or built.integers[input_id])['initial']
            for input_id in GRIP_RIDGE_INPUTS)

        assert opened == M3_GRIP

    def test_spinners_are_unitless(self, built):
        """Unitless means .value is the number shown, in mm as labelled."""
        for input_id, spec in built.spinners.items():
            assert spec['unit'] == '', f'{input_id} would need a unit conversion'

    def test_ridge_count_uses_an_integer_input(self, built):
        assert 'gripCount' in built.integers
        assert built.integers['gripCount']['min'] == 1
        assert built.integers['gripCount']['max'] == 12

    def test_input_ranges_survive_load_config(self, built, config_file):
        """Saving any spec built from the spinner limits must reload unchanged."""
        for bound in ('min', 'max'):
            spec = []
            for input_id in GRIP_RIDGE_INPUTS:
                created = built.spinners.get(input_id) or built.integers[input_id]
                spec.append(created[bound])
            spec[5] = int(spec[5])

            save_grip_ridge_insert('M3 Grip', tuple(spec), config_file)
            load_config(config_file)

            assert tm_state.GRIP_RIDGE_INSERTS['M3 Grip'] == tuple(spec), \
                f'{bound} limits were rejected by load_config'
