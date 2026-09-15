"""
Tests for the in-dialog Settings group: reading it back and writing it to config.ini.

save_values edits matching lines in place rather than round-tripping through
configparser, because that would rebuild the file and drop every comment in it.
"""

import io
from unittest.mock import MagicMock

import pytest

import tm_state
from tm_config import (
    SETTINGS_INPUTS,
    load_config,
    read_settings_inputs,
    save_settings,
    save_values,
)


def read(path):
    return io.open(path, encoding='utf-8').read()


class TestSaveValues:
    """In-place editing of config.ini."""

    def test_overwrites_an_existing_key(self, config_file):
        save_values({'Settings': {'chamfer_size': 0.8}}, config_file)

        assert 'chamfer_size = 0.8' in read(config_file)
        assert 'chamfer_size = 0.5' not in read(config_file)

    def test_keeps_comments(self, config_file):
        """A configparser round-trip would delete this line."""
        save_values({'Settings': {'chamfer_size': 0.8}}, config_file)

        assert '# Format: clearance_dia, hole_depth' in read(config_file)

    def test_keeps_insert_tables_untouched(self, config_file):
        save_values({'Settings': {'grip_chamfer_angle': 60}}, config_file)

        text = read(config_file)
        assert 'M3 x 5.7mm (standard) = 4.4, 5.7, 1.6' in text
        assert 'M3 Grip = 3.2, 7, 0.28, 1.5, 2.05, 3' in text

    def test_only_the_named_key_changes(self, config_file):
        before = read(config_file).count('\n')
        save_values({'Settings': {'chamfer_size': 0.8}}, config_file)

        after = read(config_file)
        assert after.count('\n') == before
        assert 'blind_hole_extra_depth = 1.0' in after

    def test_writes_several_sections_at_once(self, config_file):
        save_values({
            'Settings': {'chamfer_size': 0.9},
            'Developer': {'enable_logging': True},
        }, config_file)

        text = read(config_file)
        assert 'chamfer_size = 0.9' in text
        assert 'enable_logging = True' in text

    def test_adds_a_key_that_is_not_in_the_file(self, config_file):
        save_values({'Settings': {'brand_new_key': 42}}, config_file)

        text = read(config_file)
        assert 'brand_new_key = 42' in text
        # under [Settings], not appended to some other section
        settings_block = text.split('[Inserts]')[0]
        assert 'brand_new_key = 42' in settings_block

    def test_creates_a_missing_section(self, config_file):
        save_values({'Brand New Section': {'some_key': 'value'}}, config_file)

        text = read(config_file)
        assert '[Brand New Section]' in text
        assert 'some_key = value' in text

    def test_missing_file_is_not_fatal(self, tmp_path):
        path = str(tmp_path / 'does_not_exist.ini')

        assert save_values({'Settings': {'chamfer_size': 0.5}}, path) is True
        assert 'chamfer_size = 0.5' in read(path)


class TestReadSettingsInputs:
    """Reading the Settings group back off the command inputs."""

    def test_reads_each_input_value(self):
        values = {'setChamferSize': 0.8, 'setExtraDepth': 2.0,
                  'setBottomRadius': 0.3, 'setGripChamferAngle': 60.0,
                  'setShowMessage': True, 'setEnableLogging': True}
        inputs = MagicMock()
        inputs.itemById = lambda key: (MagicMock(value=values[key])
                                       if key in values else None)

        result = read_settings_inputs(inputs)

        assert result['chamfer_size'] == 0.8
        assert result['blind_hole_extra_depth'] == 2.0
        assert result['bottom_radius_size'] == 0.3
        assert result['grip_chamfer_angle'] == 60.0
        assert result['show_success_message'] is True
        assert result['enable_logging'] is True

    def test_falls_back_to_config_when_the_group_is_absent(self, monkeypatch):
        """The group is built last, so early callers must still get a full dict."""
        monkeypatch.setitem(tm_state.CONFIG, 'chamfer_size', 0.42)
        inputs = MagicMock()
        inputs.itemById = lambda key: None

        result = read_settings_inputs(inputs)

        assert result['chamfer_size'] == 0.42
        assert set(result) == {key for key, _section in SETTINGS_INPUTS.values()}


class TestSaveSettings:
    """Each setting has to land in its own config.ini section."""

    def test_routes_keys_to_their_sections(self, config_file):
        save_settings({
            'chamfer_size': 0.8,
            'show_success_message': True,
            'enable_logging': True,
        }, config_file)

        text = read(config_file)
        assert 'chamfer_size = 0.8' in text.split('[Inserts]')[0]
        assert 'show_success_message = True' in text.split('[UI State]')[1]
        assert 'enable_logging = True' in text.split('[Developer]')[1]

    def test_round_trips_through_load_config(self, config_file):
        """What the dialog saves is what the next load reads back."""
        save_settings({
            'chamfer_size': 0.8,
            'blind_hole_extra_depth': 2.5,
            'bottom_radius_size': 0.3,
            'grip_chamfer_angle': 60.0,
            'show_success_message': True,
            'enable_logging': False,
        }, config_file)

        _specs, config = load_config(config_file)

        assert config['chamfer_size'] == pytest.approx(0.8)
        assert config['blind_hole_extra_depth'] == pytest.approx(2.5)
        assert config['bottom_radius_size'] == pytest.approx(0.3)
        assert config['grip_chamfer_angle'] == pytest.approx(60.0)
        assert config['show_success_message'] is True
        assert config['enable_logging'] is False

    def test_ignores_keys_it_does_not_own(self, config_file):
        save_settings({'chamfer_size': 0.8, 'not_a_setting': 1}, config_file)

        assert 'not_a_setting' not in read(config_file)


class TestSettingsGroup:
    """The dialog group and the id -> config key map have to stay in step."""

    @pytest.fixture
    def built(self, recording_inputs):
        """Every group that holds a mapped setting, recorded flat."""
        import tm_ui
        tm_ui._addHeatInsertGroup(recording_inputs, True)
        tm_ui._addGripRidgeGroup(recording_inputs, 'M3 Grip')
        tm_ui._addGeneralGroup(recording_inputs)
        return recording_inputs

    def test_every_mapped_setting_has_an_input(self, built):
        """A drifted id would silently fall back to CONFIG and never save."""
        created = set(built.spinners) | set(built.bools)

        assert set(SETTINGS_INPUTS) <= created, (
            f'not built: {set(SETTINGS_INPUTS) - created}')

    def test_spinners_open_on_the_current_config_value(self, built, monkeypatch):
        assert built.spinners['setChamferSize']['initial'] == tm_state.CONFIG['chamfer_size']
        assert built.spinners['setGripChamferAngle']['initial'] == tm_state.CONFIG['grip_chamfer_angle']

    def test_spinners_are_unitless(self, built):
        """Unitless means .value is the number shown - no cm/radian conversion."""
        for input_id, spec in built.spinners.items():
            assert spec['unit'] == '', f'{input_id} would need a unit conversion'

    def test_every_input_has_a_tooltip(self, built):
        """Hovering has to explain what the parameter does."""
        for input_id in set(SETTINGS_INPUTS):
            assert built.tooltips.get(input_id), f'{input_id} has no tooltip'

    def test_spinner_ranges_survive_load_config(self, built, config_file):
        """Both limits of every spinner must be values load_config accepts."""
        for input_id, spec in built.spinners.items():
            if input_id not in SETTINGS_INPUTS:
                continue
            key, _section = SETTINGS_INPUTS[input_id]
            for limit in (spec['min'], spec['max']):
                save_settings({key: limit}, config_file)
                _specs, config = load_config(config_file)
                assert config[key] == pytest.approx(limit), \
                    f'{input_id} limit {limit} was rejected by load_config'
