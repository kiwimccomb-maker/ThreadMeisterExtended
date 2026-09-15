"""
Builds the whole dialog against recording fakes.

Nothing here can prove Fusion renders it, but it does prove every input is created,
lands in the right group, carries a tooltip, and that the type toggle swaps which
parameters are on screen.
"""

from unittest.mock import MagicMock

import pytest

import tm_config
import tm_state
import tm_ui


HEAT_SIZE = 'M3 x 5.7mm (standard)'
GRIP_SIZE = 'M3 Grip'


class ListItems:
    def __init__(self):
        self._items = []

    def add(self, name, isSelected, *_rest):
        item = MagicMock()
        item.name = name
        item.isSelected = isSelected
        self._items.append(item)
        return item

    def clear(self):
        self._items = []

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index]


class Input:
    """One command input, remembering where it was put and what it was told."""

    def __init__(self, input_id, kind, group=None, **spec):
        self.id = input_id
        self.kind = kind
        self.group = group
        self.spec = spec
        self.tooltip = ''
        self.isVisible = True
        self.isExpanded = True
        self.value = spec.get('initial')
        self.listItems = ListItems()
        self.children = None

    @property
    def selectedItem(self):
        for i in range(self.listItems.count):
            if self.listItems.item(i).isSelected:
                return self.listItems.item(i)
        return None

    def addSelectionFilter(self, _f):
        pass

    def setSelectionLimits(self, *_a):
        pass

    def deleteMe(self):
        pass


class Inputs:
    """A CommandInputs collection. Group children share the registry, so
    itemById finds nested inputs the way Fusion's top-level collection does."""

    def __init__(self, registry=None, group=None):
        self.registry = {} if registry is None else registry
        self.group = group

    def _add(self, input_id, kind, **spec):
        item = Input(input_id, kind, self.group, **spec)
        self.registry[input_id] = item
        return item

    def itemById(self, input_id):
        return self.registry.get(input_id)

    def addSelectionInput(self, i, n, t):
        return self._add(i, 'selection', name=n, tip=t)

    def addDropDownCommandInput(self, i, n, _style):
        return self._add(i, 'dropdown', name=n)

    def addButtonRowCommandInput(self, i, n, _multi):
        return self._add(i, 'buttonrow', name=n)

    def addRadioButtonGroupCommandInput(self, i, n):
        return self._add(i, 'radio', name=n)

    def addFloatSpinnerCommandInput(self, i, n, unit, mn, mx, step, initial):
        return self._add(i, 'float', name=n, unit=unit, min=mn, max=mx, initial=initial)

    def addIntegerSpinnerCommandInput(self, i, n, mn, mx, step, initial):
        return self._add(i, 'int', name=n, min=mn, max=mx, initial=initial)

    def addBoolValueInput(self, i, n, isCheckBox, _folder, initial):
        return self._add(i, 'checkbox' if isCheckBox else 'button',
                         name=n, initial=initial)

    def addTextBoxCommandInput(self, i, n, text, rows, ro):
        return self._add(i, 'textbox', name=n)

    def addGroupCommandInput(self, input_id, name):
        group = self._add(input_id, 'group', name=name)
        group.children = Inputs(self.registry, group=input_id)
        return group


def build_dialog(monkeypatch, last_selected):
    """Run CommandCreatedHandler.notify and hand back the registry."""
    # load_config is stubbed, so seed what it would have filled in
    monkeypatch.setattr(tm_config, 'load_config', lambda *a, **k: None)
    for name, spec in tm_config.get_default_grip_ridge_inserts().items():
        monkeypatch.setitem(tm_state.GRIP_RIDGE_INSERTS, name, spec)
    for name, spec in tm_config.get_default_inserts().items():
        monkeypatch.setitem(tm_state.INSERT_SPECS, name, spec)
    monkeypatch.setitem(tm_state.CONFIG, 'last_selected_insert', last_selected)
    monkeypatch.setattr(tm_ui, 'updateInfoText', lambda inputs: None)
    monkeypatch.setattr(tm_state, '_ui', MagicMock())

    inputs = Inputs()
    cmd = MagicMock()
    cmd.commandInputs = inputs
    args = MagicMock()
    args.command = cmd

    tm_ui.CommandCreatedHandler().notify(args)
    assert not tm_state._ui.messageBox.called, tm_state._ui.messageBox.call_args
    return inputs, cmd


@pytest.fixture
def heat_dialog(monkeypatch):
    return build_dialog(monkeypatch, HEAT_SIZE)[0]


@pytest.fixture
def grip_dialog(monkeypatch):
    return build_dialog(monkeypatch, GRIP_SIZE)[0]


class TestItBuilds:

    def test_every_input_the_rest_of_the_code_looks_up_exists(self, grip_dialog):
        expected = {'bodySelect', 'pointSelect', 'insertType', 'insertSize',
                    'holeType', 'addChamfer', 'addBottomRadius', 'infoText'}
        expected |= set(tm_config.SETTINGS_INPUTS)
        expected |= set(tm_config.GRIP_RIDGE_INPUTS)
        expected |= set(tm_ui.ACTION_ROWS)

        missing = expected - set(grip_dialog.registry)
        assert not missing, f'not built: {sorted(missing)}'

    def test_the_dialog_is_not_taller_than_a_laptop_screen(self, monkeypatch):
        """A 600px minimum height put the window off the bottom on first open."""
        _inputs, cmd = build_dialog(monkeypatch, GRIP_SIZE)

        _width, height = cmd.setDialogMinimumSize.call_args[0]
        assert height <= 400, f'minimum height {height} is too tall to place'


class TestInsertTypeToggle:

    def test_the_toggle_offers_both_families(self, heat_dialog):
        toggle = heat_dialog.itemById('insertType')
        names = [toggle.listItems.item(i).name for i in range(toggle.listItems.count)]

        assert names == [tm_ui.INSERT_TYPE_HEAT, tm_ui.INSERT_TYPE_GRIP]

    def test_it_opens_on_the_family_of_the_remembered_size(self, grip_dialog):
        assert tm_ui._isGripSelected(grip_dialog)

    def test_the_size_list_holds_only_that_family(self, grip_dialog):
        dropdown = grip_dialog.itemById('insertSize')
        names = {dropdown.listItems.item(i).name for i in range(dropdown.listItems.count)}

        assert names == set(tm_state.GRIP_RIDGE_INSERTS)
        assert not names & set(tm_state.INSERT_SPECS)

    def test_heat_opens_with_only_heat_sizes(self, heat_dialog):
        dropdown = heat_dialog.itemById('insertSize')
        names = {dropdown.listItems.item(i).name for i in range(dropdown.listItems.count)}

        assert names == set(tm_state.INSERT_SPECS)


class TestOnlyOneFamilysParametersShow:

    def test_grip_selected_hides_the_heat_group(self, grip_dialog):
        assert grip_dialog.itemById('gripRidgeGroup').isVisible
        assert not grip_dialog.itemById('heatInsertGroup').isVisible

    def test_heat_selected_hides_the_grip_group(self, heat_dialog):
        assert heat_dialog.itemById('heatInsertGroup').isVisible
        assert not heat_dialog.itemById('gripRidgeGroup').isVisible

    def test_switching_type_swaps_them(self, heat_dialog):
        tm_ui._applyTypeVisibility(heat_dialog, True)

        assert heat_dialog.itemById('gripRidgeGroup').isVisible
        assert not heat_dialog.itemById('heatInsertGroup').isVisible


class TestGrouping:

    def test_chamfer_and_fillet_toggles_moved_into_heat_parameters(self, heat_dialog):
        assert heat_dialog.itemById('addChamfer').group == 'heatInsertGroup'
        assert heat_dialog.itemById('addBottomRadius').group == 'heatInsertGroup'

    def test_chamfer_angle_lives_with_the_grip_ridges(self, grip_dialog):
        """It only affects grip ridges, so it belongs in their group."""
        assert grip_dialog.itemById('setGripChamferAngle').group == 'gripShapeGroup'

    def test_hole_depth_is_top_level_in_the_grip_group(self, grip_dialog):
        """The one regularly edited, so not behind a collapsed sub-group."""
        assert grip_dialog.itemById('gripEdgeDepth').group == 'gripRidgeGroup'

    def test_the_rest_of_the_ridge_shape_is_tucked_away(self, grip_dialog):
        for input_id in ('gripClearanceDia', 'gripRidgeDia', 'gripArcDistance',
                         'gripCount', 'gripEdgeChamfer'):
            assert grip_dialog.itemById(input_id).group == 'gripShapeGroup', input_id
        assert not grip_dialog.itemById('gripShapeGroup').isExpanded

    def test_ridge_shape_is_not_nested_inside_another_group(self, grip_dialog):
        """Fusion raises "the group cannot be folded" for a group inside a group,
        and draws it as a stray label instead."""
        assert grip_dialog.itemById('gripShapeGroup').group is None
        assert grip_dialog.itemById('gripRidgeGroup').group is None

    def test_the_grip_groups_hide_together(self, heat_dialog):
        for input_id in tm_ui.GRIP_ONLY_INPUTS:
            assert not heat_dialog.itemById(input_id).isVisible, input_id


class TestTooltips:

    @pytest.mark.parametrize('input_id', sorted(
        set(tm_config.GRIP_RIDGE_INPUTS) | {'setGripChamferAngle'}))
    def test_every_grip_parameter_explains_itself(self, grip_dialog, input_id):
        assert len(grip_dialog.itemById(input_id).tooltip) > 20, 'needs a real explanation'

    def test_the_offset_tooltip_says_which_way_it_moves_the_ridge(self, grip_dialog):
        said = grip_dialog.itemById('gripArcDistance').tooltip
        assert 'further out' in said and 'less' in said

    def test_the_diameter_tooltip_says_a_bigger_ridge_protrudes_more(self, grip_dialog):
        said = grip_dialog.itemById('gripRidgeDia').tooltip
        assert 'protrudes' in said and 'more' in said


class TestActionButtons:

    @pytest.mark.parametrize('row_id', sorted(tm_ui.ACTION_ROWS))
    def test_actions_sit_on_one_row(self, grip_dialog, row_id):
        """Side by side, not three stacked inputs."""
        assert grip_dialog.itemById(row_id).kind == 'buttonrow'

    def test_each_parameter_group_offers_all_three(self, grip_dialog):
        for row_id in ('heatActions', 'gripActions'):
            row = grip_dialog.itemById(row_id)
            labels = [row.listItems.item(i).name for i in range(row.listItems.count)]
            assert labels == [label for label, _icon, _suffix in tm_ui.ACTIONS]

    def test_the_row_carries_no_label_of_its_own(self, grip_dialog):
        """The label column repeated what was already on the buttons."""
        assert grip_dialog.itemById('gripActions').spec['name'] == ''

    def test_nothing_starts_pressed(self, grip_dialog):
        row = grip_dialog.itemById('gripActions')
        assert not any(row.listItems.item(i).isSelected
                       for i in range(row.listItems.count))


class TestIcons:
    """A button row draws the icon, so every item needs one that is really there."""

    @pytest.mark.parametrize('folder', [
        tm_ui.HEAT_ICONS, tm_ui.GRIP_ICONS, tm_ui.BLIND_ICONS, tm_ui.THROUGH_ICONS,
    ] + [icon for _label, icon, _suffix in tm_ui.ACTIONS])
    def test_the_icon_folder_has_every_size_fusion_looks_for(self, folder):
        import os
        root = os.path.join(os.path.dirname(__file__), '..')
        for size in (16, 32, 64, 128):
            path = os.path.join(root, folder, f'{size}x{size}.png')
            assert os.path.isfile(path), f'missing {folder}/{size}x{size}.png'


class TestHoleType:

    def test_it_is_a_side_by_side_button_row(self, heat_dialog):
        assert heat_dialog.itemById('holeType').kind == 'buttonrow'

    def test_exactly_one_option_is_selected(self, heat_dialog):
        holeType = heat_dialog.itemById('holeType')
        selected = [holeType.listItems.item(i).isSelected
                    for i in range(holeType.listItems.count)]

        assert sum(selected) == 1, 'mutually exclusive'
        assert len(selected) == 2
