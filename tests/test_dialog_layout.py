"""
Builds the whole dialog against recording fakes.

Nothing here can prove Fusion renders it, but it does prove every input is created,
lands in the right group, carries a tooltip, and that the type toggle swaps which
parameters are on screen.
"""

import io
import os
from unittest.mock import MagicMock

import pytest

import adsk
import tm_config
import tm_state
import tm_ui


HERE = os.path.dirname(__file__)
EMPTY_TOOLTIP = ''
HEAT_SIZE = 'M3 x 5.7mm (standard)'
GRIP_SIZE = 'M3 Grip'


class ListItems:
    def __init__(self):
        self._items = []

    def add(self, name, isSelected, folder=None):
        item = MagicMock()
        item.name = name
        item.isSelected = isSelected
        item.folder = folder
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
        self.commandInputs = None
        self.cells = []

    def addCommandInput(self, item, row, column):
        self.cells.append((item.id, row, column))

    # Fusion enums are MagicMocks under test, so just remember what was set
    tablePresentationStyle = None
    hasGrid = None

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
    """A CommandInputs collection.

    Group children share the registry, so itemById finds them the way Fusion's
    top-level collection does. Table cells deliberately do not: Fusion will not
    find those either, and pretending otherwise is what let two pickers ship
    broken. Use `everything` to reach them from a test.
    """

    def __init__(self, registry=None, everything=None, group=None, in_table=False):
        self.registry = {} if registry is None else registry
        self.everything = {} if everything is None else everything
        self.group = group
        self.in_table = in_table

    def _add(self, input_id, kind, **spec):
        item = Input(input_id, kind, self.group, **spec)
        self.everything[input_id] = item
        if not self.in_table:
            self.registry[input_id] = item
        return item

    def itemById(self, input_id):
        return self.registry.get(input_id)

    def cell(self, input_id):
        """An input wherever it is, including inside a table."""
        return self.everything.get(input_id)

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
        return self._add(i, 'textbox', name=n, text=text, readonly=ro)

    def addGroupCommandInput(self, input_id, name):
        group = self._add(input_id, 'group', name=name)
        group.children = Inputs(self.registry, self.everything, group=input_id)
        return group

    def addTableCommandInput(self, input_id, name, columns, ratio):
        table = self._add(input_id, 'table', name=name, columns=columns, ratio=ratio)
        # Fusion creates a table's cell contents in its own commandInputs, and
        # does not find them from the command's collection afterwards
        table.commandInputs = Inputs(self.registry, self.everything,
                                     group=input_id, in_table=True)
        return table


def build_dialog(monkeypatch, last_selected):
    """Run CommandCreatedHandler.notify and hand back the registry."""
    # load_config is stubbed, so seed what it would have filled in
    monkeypatch.setattr(tm_config, 'load_config', lambda *a, **k: None)
    for name, spec in tm_config.get_default_grip_ridge_inserts().items():
        monkeypatch.setitem(tm_state.GRIP_RIDGE_INSERTS, name, spec)
    for name, spec in tm_config.get_default_inserts().items():
        monkeypatch.setitem(tm_state.INSERT_SPECS, name, spec)
    monkeypatch.setitem(tm_state.CONFIG, 'last_selected_insert', last_selected)
    # The dialog both reads and writes this one, so pin it per test
    monkeypatch.setitem(tm_state.CONFIG, 'hole_type_blind', True)
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
                    'holeType', 'addChamfer', 'addBottomRadius',
                    'infoText'}
        expected |= set(tm_config.SETTINGS_INPUTS)
        expected |= set(tm_config.GRIP_RIDGE_INPUTS)
        expected |= set(tm_ui.ACTION_BUTTONS)

        missing = expected - set(grip_dialog.everything)
        assert not missing, f'not built: {sorted(missing)}'

    def test_nothing_the_code_looks_up_by_id_hides_in_a_table(self):
        """Fusion does not find a table's contents from the command's inputs, so
        anything read that way has to be at the top level or in a group."""
        source = (io.open(os.path.join(HERE, '..', 'core', 'tm_ui.py'),
                          encoding='utf-8').read()
                  + io.open(os.path.join(HERE, '..', 'core', 'tm_execute.py'),
                            encoding='utf-8').read())
        in_tables = set(tm_ui.ACTION_BUTTONS)

        for input_id in sorted(in_tables):
            assert f"itemById('{input_id}')" not in source, (
                f'{input_id} lives in a table; itemById will not find it')

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

    def test_each_family_shows_its_name_beside_its_icon(self, heat_dialog):
        """A button row would have drawn the icons alone, with the name only on
        hover - which is why both looked like they said the same thing."""
        toggle = heat_dialog.itemById('insertType')
        pairs = [(toggle.listItems.item(i).name, toggle.listItems.item(i).folder)
                 for i in range(toggle.listItems.count)]

        assert pairs == [(tm_ui.INSERT_TYPE_HEAT, tm_ui.HEAT_ICONS),
                         (tm_ui.INSERT_TYPE_GRIP, tm_ui.GRIP_ICONS)]

    def test_the_tooltip_covers_both_families(self, heat_dialog):
        said = heat_dialog.itemById('insertType').tooltip
        assert tm_ui.INSERT_TYPE_HEAT in said and tm_ui.INSERT_TYPE_GRIP in said

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


class TestLabelPadding:
    """Fusion gives the value box whatever the label column does not take, and
    offers no ratio, so the labels are padded to hold the boxes back."""

    def parameters(self, dialog):
        ids = set(tm_config.GRIP_RIDGE_INPUTS) | set(tm_config.SETTINGS_INPUTS)
        return {i: dialog.itemById(i) for i in ids
                if dialog.itemById(i).kind in ('float', 'int')}

    def test_every_parameter_label_is_padded(self, grip_dialog):
        for input_id, item in self.parameters(grip_dialog).items():
            assert item.spec['name'].endswith(tm_ui.LABEL_PAD), input_id

    def test_the_padding_is_not_the_whole_label(self, grip_dialog):
        """It has to still read as words, not as a gap."""
        for input_id, item in self.parameters(grip_dialog).items():
            visible = item.spec['name'].replace(tm_ui.LABEL_PAD, '').strip()
            assert len(visible) > 3, f'{input_id} reads as {visible!r}'

    def test_the_padding_is_non_breaking(self):
        """Plain trailing spaces are the sort of thing a UI trims off before they
        can widen anything."""
        assert tm_ui.LABEL_PAD
        assert set(tm_ui.LABEL_PAD) == {' '}


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

    @pytest.mark.parametrize('button', sorted(tm_ui.ACTION_BUTTONS))
    def test_actions_are_labelled_buttons(self, grip_dialog, button):
        """Words on the button: not an icon, and not a checkbox."""
        item = grip_dialog.cell(button)
        assert item.kind == 'button'
        assert item.spec['name']

    @pytest.mark.parametrize('button', sorted(tm_ui.ACTION_BUTTONS))
    def test_actions_carry_no_tooltip(self, grip_dialog, button):
        """The label already says it; a tooltip would only repeat it."""
        assert grip_dialog.cell(button).tooltip == EMPTY_TOOLTIP

    def test_each_parameter_group_offers_all_three(self, grip_dialog):
        for prefix in ('heat', 'grip'):
            for _label, suffix in tm_ui.ACTIONS:
                assert grip_dialog.cell(prefix + suffix) is not None

    def test_they_share_one_line(self, grip_dialog):
        """A table is what puts them side by side while keeping their labels."""
        for table_id in ('heatActions', 'gripActions'):
            table = grip_dialog.itemById(table_id)
            assert table.kind == 'table'
            # all three in row 0, one per column
            assert sorted(table.cells, key=lambda c: c[2]) == [
                (table_id[:-len('Actions')] + suffix, 0, column)
                for column, (_label, suffix) in enumerate(tm_ui.ACTIONS)]

    def test_nothing_starts_pressed(self, grip_dialog):
        for button in tm_ui.ACTION_BUTTONS:
            assert grip_dialog.cell(button).value is False

    def test_the_shortest_label_still_gets_room_for_itself(self, grip_dialog):
        """Sizing purely by label length left Save too narrow for the word."""
        ratio = [int(part) for part
                 in grip_dialog.itemById('gripActions').spec['ratio'].split(':')]
        share = min(ratio) / sum(ratio)

        assert share > 0.2, f'the narrowest column is only {share:.0%} of the row'

    def test_the_widest_label_gets_the_widest_column(self, grip_dialog):
        """Equal columns clipped "Restore User Saved" to "Restore User Sav..."."""
        ratio = [int(part)
                 for part in grip_dialog.itemById('gripActions').spec['ratio'].split(':')]
        widest = max(range(len(tm_ui.ACTIONS)), key=lambda i: len(tm_ui.ACTIONS[i][0]))

        assert ratio.index(max(ratio)) == widest

    def test_the_buttons_are_outlined(self, grip_dialog):
        """Borders, so they read as buttons rather than loose words."""
        table = grip_dialog.itemById('gripActions')
        expected = adsk.core.TablePresentationStyles.itemBorderTablePresentationStyle

        assert table.tablePresentationStyle is expected


class TestIcons:
    """A button row draws the icon, so every item needs one that is really there.
    The insert type toggle is the only row left that uses them."""

    @pytest.mark.parametrize('folder', [tm_ui.HEAT_ICONS, tm_ui.GRIP_ICONS])
    def test_the_icon_folder_has_every_size_fusion_looks_for(self, folder):
        import os
        root = os.path.join(os.path.dirname(__file__), '..')
        for size in (16, 32, 64, 128):
            path = os.path.join(root, folder, f'{size}x{size}.png')
            assert os.path.isfile(path), f'missing {folder}/{size}x{size}.png'


class TestHoleType:
    """Two labelled, mutually exclusive options that show which one is in force.

    Not two buttons: Fusion will not rename a live input, so a button has
    nowhere to say it is the chosen one, and greying it instead read as
    unavailable and could not be clicked.
    """

    def test_it_is_a_radio_group(self, heat_dialog):
        assert heat_dialog.itemById('holeType').kind == 'radio'

    def test_the_code_can_find_it(self, heat_dialog):
        """A table would hide it from itemById, which is how the last two
        pickers shipped broken."""
        assert heat_dialog.itemById('holeType') is not None

    def test_each_option_says_what_it_is(self, heat_dialog):
        group = heat_dialog.itemById('holeType')

        assert [group.listItems.item(i).name
                for i in range(group.listItems.count)] == list(
                    tm_ui.HOLE_TYPE_LABELS)

    def test_exactly_one_is_chosen(self, heat_dialog):
        group = heat_dialog.itemById('holeType')
        chosen = [group.listItems.item(i).isSelected
                  for i in range(group.listItems.count)]

        assert sum(chosen) == 1, 'mutually exclusive'


class TestHoleTypeChoice:
    """Whichever is chosen is mirrored into CONFIG, which is what the cut reads."""

    def choose(self, dialog, label):
        group = dialog.itemById('holeType')
        for i in range(group.listItems.count):
            item = group.listItems.item(i)
            item.isSelected = (item.name == label)

    def test_it_opens_on_the_remembered_choice(self, heat_dialog):
        group = heat_dialog.itemById('holeType')

        assert group.selectedItem.name == tm_ui.HOLE_TYPE_LABELS[0]
        assert tm_state.CONFIG['hole_type_blind'] is True

    def test_choosing_through_turns_blind_off(self, heat_dialog):
        self.choose(heat_dialog, tm_ui.HOLE_TYPE_LABELS[1])

        tm_ui._holeTypeChanged(heat_dialog)

        assert tm_state.CONFIG['hole_type_blind'] is False

    def test_choosing_blind_turns_it_back_on(self, heat_dialog):
        self.choose(heat_dialog, tm_ui.HOLE_TYPE_LABELS[1])
        tm_ui._holeTypeChanged(heat_dialog)

        self.choose(heat_dialog, tm_ui.HOLE_TYPE_LABELS[0])
        tm_ui._holeTypeChanged(heat_dialog)

        assert tm_state.CONFIG['hole_type_blind'] is True

    def test_the_cut_follows_the_control_not_a_stale_mirror(self, heat_dialog,
                                                            monkeypatch):
        """CONFIG used to be kept in step by the InputChanged event. When that
        fired for a button nobody pressed, the cut came out the hole type the
        dialog was not showing."""
        self.choose(heat_dialog, tm_ui.HOLE_TYPE_LABELS[0])
        monkeypatch.setitem(tm_state.CONFIG, 'hole_type_blind', False)

        assert tm_config.read_hole_type(heat_dialog) is True

    def test_it_falls_back_to_the_remembered_choice_before_the_dialog_exists(
            self, monkeypatch):
        monkeypatch.setitem(tm_state.CONFIG, 'hole_type_blind', False)

        assert tm_config.read_hole_type(Inputs()) is False

    def test_it_opens_on_through_when_that_was_last_used(self, monkeypatch):
        """The last hole type used is remembered in config.ini, so the dialog
        has to come back up on it rather than resetting to blind."""
        monkeypatch.setitem(tm_state.CONFIG, 'hole_type_blind', True)

        group = tm_ui._addHoleTypeInput(Inputs(), blind_first=False)

        assert group.selectedItem.name == tm_ui.HOLE_TYPE_LABELS[1]
        assert tm_state.CONFIG['hole_type_blind'] is False
