"""
tm_ui.py – UI event handlers and dialog helper.

Handles CommandCreated, InputChanged, ValidateInputs events and
the updateInfoText helper that refreshes the info text box.
"""
import adsk.core, adsk.fusion, traceback
import tm_helpers
import tm_state
import tm_config
from tm_helpers import calc_blind_hole_depth_mm
from tm_execute import CommandExecuteHandler


# The two insert families the dialog switches between
INSERT_TYPE_HEAT = 'Heat-Set Insert'
INSERT_TYPE_GRIP = 'Grip Ridge'

# Button row icons, resolved by Fusion relative to the add-in folder
HEAT_ICONS = 'resources/icons/heatset'
GRIP_ICONS = 'resources/icons/gripridge'
BLIND_ICONS = 'resources/icons/blindhole'
THROUGH_ICONS = 'resources/icons/throughhole'

# The actions every parameter group offers, as one row: label -> (icon, suffix).
# A button row shows the icon and uses the label as its tooltip, which keeps the
# text out of the label column where it used to appear twice.
ACTIONS = (
    ('Restore Defaults', 'resources/icons/restoredefaults', 'RestoreDefaults'),
    ('Save', 'resources/icons/save', 'Save'),
    ('Restore User Saved', 'resources/icons/restoresaved', 'RestoreSaved'),
)

# Shown only while the Grip Ridge family is chosen. Two groups rather than one
# because Fusion will not fold a group nested inside another group.
GRIP_ONLY_INPUTS = ('gripRidgeGroup', 'gripShapeGroup', 'gripActions')

# Rows whose buttons act immediately and then clear their own selection
ACTION_ROWS = ('heatActions', 'gripActions', 'generalActions')

# Anything that changes what the info panel should say
REFRESH_INFO_ON = (
    ('insertType', 'insertSize', 'holeType', 'addChamfer')
    + tuple(tm_config.SETTINGS_INPUTS)
    + tm_config.GRIP_RIDGE_INPUTS
    + ACTION_ROWS
)


class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            # Reload config to pick up any saved changes
            tm_config.load_config()

            cmd = args.command
            
            # Keep the dialog small enough to land on screen. A 600px minimum
            # height pushed the window off the bottom on a fresh session; the
            # parameters now sit in groups that start collapsed, so it fits.
            cmd.setDialogMinimumSize(320, 300)
            try:
                cmd.setDialogInitialSize(400, 560)
            except Exception:
                pass

            onExecute = CommandExecuteHandler()
            cmd.execute.add(onExecute)

            onInputChanged = InputChangedHandler()
            cmd.inputChanged.add(onInputChanged)

            onValidateInputs = ValidateInputsHandler()
            cmd.validateInputs.add(onValidateInputs)

            # Held on self (which tm_state._handlers keeps alive) rather than
            # appended to that list, which grew on every dialog open.
            self._cmdHandlers = [onExecute, onInputChanged, onValidateInputs]

            inputs = cmd.commandInputs

            # Target body selection
            bodySelect = inputs.addSelectionInput(
                'bodySelect', 'Target Body', 'Select the solid body to cut into')
            bodySelect.addSelectionFilter('SolidBodies')
            bodySelect.setSelectionLimits(1, 1)

            # Sketch point selection
            pointSelect = inputs.addSelectionInput(
                'pointSelect', 'Sketch Point(s)',
                'Select sketch point(s) where holes will be created')
            pointSelect.addSelectionFilter('SketchPoints')
            pointSelect.setSelectionLimits(1, 0)

            # Insert type: the two families have different parameters, so this
            # decides both the size list and which parameter group is on screen.
            lastSelected = tm_state.CONFIG.get('last_selected_insert', '')
            isGrip = lastSelected in tm_state.GRIP_RIDGE_INSERTS
            _addToggleRow(
                inputs, 'insertType', 'Insert Type',
                [(INSERT_TYPE_HEAT, HEAT_ICONS), (INSERT_TYPE_GRIP, GRIP_ICONS)],
                1 if isGrip else 0,
                'Heat-set inserts are melted into a plain bore. Grip ridges are '
                'printed ridges a screw forms its own thread against.')

            # Insert size, refilled whenever the type changes
            insertDropdown = inputs.addDropDownCommandInput(
                'insertSize', 'Insert Size',
                adsk.core.DropDownStyles.TextListDropDownStyle)
            insertDropdown.tooltip = (
                'Which size to cut. The list follows the insert type above.')
            _fillInsertDropdown(insertDropdown, isGrip, lastSelected)
            lastSelected = _selectedName(insertDropdown) or lastSelected

            # Hole type, side by side and mutually exclusive
            _addToggleRow(
                inputs, 'holeType', 'Hole Type',
                [('Blind Hole', BLIND_ICONS), ('Through Hole', THROUGH_ICONS)],
                0 if tm_state.CONFIG.get('hole_type_blind', True) else 1,
                'Blind stops at the calculated depth. Through cuts the whole body.')

            _addHeatInsertGroup(inputs, not isGrip)
            _addGripRidgeGroup(inputs, lastSelected)
            _addGeneralGroup(inputs)

            # Info text
            inputs.addTextBoxCommandInput('infoText', '', '', 5, True)

            # Developer: debug export (only visible when enabled in config.ini)
            if tm_state.CONFIG.get('enable_debug_export', False):
                inputs.addBoolValueInput(
                    'exportDebug',
                    'Export Debug JSON (saves fixture to debug_exports/)',
                    True, '', False)

            # Last, so the info text reflects every group's values
            updateInfoText(inputs)

        except Exception:
            tm_state._ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


class InputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            changedInput = args.input
            # Deliberately not args.inputs: for an input inside a group, that is the
            # group's own children, in which the top-level ids do not exist. Reading
            # it was what made Restore Defaults raise AttributeError on
            # itemById('insertSize').
            inputs = args.firingEvent.sender.commandInputs
            changedId = changedInput.id

            # Auto-focus on point selection after body is selected
            if changedId == 'bodySelect':
                bodySelect = inputs.itemById('bodySelect')
                if bodySelect and bodySelect.selectionCount > 0:
                    pointSelect = inputs.itemById('pointSelect')
                    if pointSelect:
                        pointSelect.isEnabled = True
                        pointSelect.hasFocus = True

            # Switching family refills the size list and swaps the visible group
            if changedId == 'insertType':
                isGrip = _isGripSelected(inputs)
                dropdown = inputs.itemById('insertSize')
                if dropdown:
                    _fillInsertDropdown(
                        dropdown, isGrip, tm_state.CONFIG.get('last_selected_insert', ''))
                    _loadGripSpec(inputs, _selectedName(dropdown))
                _applyTypeVisibility(inputs, isGrip)

            # A different size within the same family
            if changedId == 'insertSize':
                _loadGripSpec(inputs, _selectedName(inputs.itemById('insertSize')))

            # Action buttons act at once so the result is visible, then release
            # so none is left looking held down.
            if changedId in ACTION_ROWS:
                pressed = _selectedName(changedInput)
                if pressed:
                    _runAction(inputs, changedId[:-len('Actions')], pressed)
                    _clearRowSelection(changedInput)

            if changedId in REFRESH_INFO_ON:
                updateInfoText(inputs)

        except Exception:
            tm_state._ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


class ValidateInputsHandler(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        try:
            inputs = args.inputs
            bodySelect = inputs.itemById('bodySelect')
            pointSelect = inputs.itemById('pointSelect')

            if bodySelect.selectionCount == 0 or pointSelect.selectionCount == 0:
                args.areInputsValid = False
            else:
                args.areInputsValid = True

        except Exception:
            tm_state._ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


def _setValue(inputs, input_id, value):
    """Set a command input's value if that input exists."""
    command_input = inputs.itemById(input_id)
    if command_input:
        command_input.value = value


def _valueOf(inputs, input_id, fallback):
    command_input = inputs.itemById(input_id)
    return command_input.value if command_input else fallback


def _selectedName(listInput):
    """The selected item's name, or None if nothing is selected."""
    if not listInput:
        return None
    item = listInput.selectedItem
    return item.name if item else None


def _isGripSelected(inputs):
    """True when the Grip Ridge family is chosen."""
    return _selectedName(inputs.itemById('insertType')) == INSERT_TYPE_GRIP


def _fillInsertDropdown(dropdown, is_grip, preferred=None):
    """Refill the size list for one insert family, keeping the preferred size."""
    names = list(tm_state.GRIP_RIDGE_INSERTS if is_grip else tm_state.INSERT_SPECS)
    items = dropdown.listItems
    items.clear()
    for name in names:
        items.add(name, name == preferred)
    if items.count and not any(items.item(i).isSelected for i in range(items.count)):
        items.item(0).isSelected = True


def _addToggleRow(inputs, input_id, label, items, selected_index, tooltip):
    """Mutually exclusive buttons, side by side.

    `items` is a list of (name, icon folder); a button row draws the icon and uses
    the name as its tooltip. Falls back to a radio group, which draws the name,
    if this build will not make a button row, so the dialog always opens.
    """
    try:
        row = inputs.addButtonRowCommandInput(input_id, label, False)
        for index, (name, folder) in enumerate(items):
            row.listItems.add(name, index == selected_index, folder)
    except Exception:
        existing = inputs.itemById(input_id)
        if existing:
            existing.deleteMe()
        row = inputs.addRadioButtonGroupCommandInput(input_id, label)
        for index, (name, _folder) in enumerate(items):
            row.listItems.add(name, index == selected_index)
    row.tooltip = tooltip
    return row


def _addActionButtons(children, prefix, actions=ACTIONS):
    """One row of action buttons for a parameter group.

    A row rather than separate inputs so they sit side by side, and because a
    bool input styled as a button repeats its label in the label column as well
    as on the button itself.
    """
    row_id = prefix + 'Actions'
    try:
        row = children.addButtonRowCommandInput(row_id, '', False)
        for label, folder, _suffix in actions:
            row.listItems.add(label, False, folder)
    except Exception:
        existing = children.itemById(row_id)
        if existing:
            existing.deleteMe()
        row = children.addRadioButtonGroupCommandInput(row_id, '')
        for label, _folder, _suffix in actions:
            row.listItems.add(label, False)
    row.tooltip = ('Restore Defaults loads the shipped values, Save writes what is '
                   'on screen to config.ini, Restore User Saved goes back to what '
                   'is in config.ini.')
    return row


def _clearRowSelection(row):
    """Leave no button looking held down after it has acted."""
    for index in range(row.listItems.count):
        item = row.listItems.item(index)
        if item.isSelected:
            item.isSelected = False


def _addHeatInsertGroup(inputs, visible):
    """Parameters that only apply to plain heat-set insert bores."""
    group = inputs.addGroupCommandInput('heatInsertGroup', 'Heat Insert Parameters')
    group.isExpanded = False
    children = group.children

    chamfer = children.addBoolValueInput(
        'addChamfer', 'Add Chamfer', True, '',
        tm_state.CONFIG['chamfer_enabled_default'])
    chamfer.tooltip = ('Break the sharp top edge of the bore so the insert starts '
                       'straight. Its size is added to the blind hole depth.')

    fillet = children.addBoolValueInput(
        'addBottomRadius', 'Add Bottom Fillet', True, '',
        tm_state.CONFIG['bottom_radius_enabled_default'])
    fillet.tooltip = ('Round the bottom of a blind hole, which prints more cleanly '
                      'than a sharp corner. Blind holes only.')

    size = children.addFloatSpinnerCommandInput(
        'setChamferSize', 'Chamfer (mm)', '', 0.1, 5.0, 0.1,
        tm_state.CONFIG['chamfer_size'])
    size.tooltip = ('How far the top chamfer cuts back. Larger gives the insert an '
                    'easier start but leaves less material around the mouth.')

    depth = children.addFloatSpinnerCommandInput(
        'setExtraDepth', 'Extra Depth (mm)', '', 0.0, 10.0, 0.1,
        tm_state.CONFIG['blind_hole_extra_depth'])
    depth.tooltip = ('Clearance cut below the insert so it seats fully and displaced '
                     'plastic has somewhere to go.')

    radius = children.addFloatSpinnerCommandInput(
        'setBottomRadius', 'Fillet Radius (mm)', '', 0.0, 5.0, 0.1,
        tm_state.CONFIG['bottom_radius_size'])
    radius.tooltip = 'Radius of the bottom fillet, when Add Bottom Fillet is on.'

    _addActionButtons(children, 'heat')
    group.isVisible = visible
    return group


def _addGripRidgeGroup(inputs, insert_name):
    """Per-insert grip ridge geometry from [GripRidgeInserts].

    Two top-level groups, not one with a sub-group: Fusion refuses to fold a group
    nested inside another group ("the group cannot be folded"), and renders it as a
    stray label instead. So Ridge Shape is a sibling of Grip Ridge Parameters.

    Hole depth stays out in the open because it is the one regularly changed;
    everything defining the ridge shape sits in Ridge Shape, which starts closed.
    Unitless spinners, mm as labelled, min/max mirroring load_config().
    """
    spec = tm_state.GRIP_RIDGE_INSERTS.get(insert_name)
    if spec is None:
        # Hidden anyway, but the inputs still need starting values
        spec = next(iter(tm_state.GRIP_RIDGE_INSERTS.values()),
                    (3.2, 7, 0.28, 1.5, 2.05, 3))
    clearance, depth, chamfer, ridge_dia, arc_distance, count = spec

    group = inputs.addGroupCommandInput('gripRidgeGroup', 'Grip Ridge Parameters')
    holeDepth = group.children.addFloatSpinnerCommandInput(
        'gripEdgeDepth', 'Hole Depth (mm)', '', 0.1, 100.0, 0.5, depth)
    holeDepth.tooltip = ('How deep to cut. The usual thing to change: deeper gives '
                         'the screw more ridge to bite into, within the wall '
                         'thickness you have.')

    shape = inputs.addGroupCommandInput('gripShapeGroup', 'Ridge Shape')
    shape.isExpanded = False
    shaped = shape.children

    clearanceInput = shaped.addFloatSpinnerCommandInput(
        'gripClearanceDia', 'Clearance \u00d8 (mm)', '', 0.1, 50.0, 0.1, clearance)
    clearanceInput.tooltip = ('Diameter of the plain bore the ridges sit in. It should '
                              'clear the screw; the ridges do the gripping, not the bore.')

    ridgeInput = shaped.addFloatSpinnerCommandInput(
        'gripRidgeDia', 'Ridge \u00d8 (mm)', '', 0.1, 20.0, 0.1, ridge_dia)
    ridgeInput.tooltip = ('Diameter of each ridge circle. Larger makes a fatter ridge '
                          'that necessarily protrudes further into the bore, so the '
                          'screw cuts more thread but drives harder.')

    offsetInput = shaped.addFloatSpinnerCommandInput(
        'gripArcDistance', 'Ridge Offset (mm)', '', 0.1, 50.0, 0.05, arc_distance)
    offsetInput.tooltip = ('How far each ridge circle sits from the hole centre. '
                           'Moving it further out pulls the ridge back towards the '
                           'bore wall, so it protrudes into the bore less.')

    countInput = shaped.addIntegerSpinnerCommandInput(
        'gripCount', 'Ridge Count', 1, 12, 1, int(count))
    countInput.tooltip = ('How many ridges around the bore. More spreads the load, '
                          'but too many for the diameter run into each other.')

    chamferInput = shaped.addFloatSpinnerCommandInput(
        'gripEdgeChamfer', 'Ridge Chamfer (mm)', '', 0.0, 5.0, 0.05, chamfer)
    chamferInput.tooltip = ('Break the top edge of each ridge so the screw leads in '
                            'instead of catching on it.')

    angleInput = shaped.addFloatSpinnerCommandInput(
        'setGripChamferAngle', 'Chamfer Angle (deg)', '', 15.0, 85.0, 1.0,
        tm_state.CONFIG['grip_chamfer_angle'])
    angleInput.tooltip = ('Angle of that lead-in, measured from the face. Shallower '
                          'gives a longer, gentler lead-in.')

    # Below both groups, so they act on everything above them
    _addActionButtons(inputs, 'grip')

    _applyTypeVisibility(inputs, insert_name in tm_state.GRIP_RIDGE_INSERTS)
    return group


def _addGeneralGroup(inputs):
    """Options that apply whichever insert type is chosen."""
    group = inputs.addGroupCommandInput('generalGroup', 'General')
    group.isExpanded = False
    children = group.children

    message = children.addBoolValueInput(
        'setShowMessage', 'Show Success Message', True, '',
        tm_state.CONFIG.get('show_success_message', True))
    message.tooltip = 'Confirm with a dialog after a run that had no failures.'

    logging = children.addBoolValueInput(
        'setEnableLogging', 'Enable Logging', True, '',
        tm_state.CONFIG.get('enable_logging', False))
    logging.tooltip = 'Write diagnostics to the Text Commands palette.'

    _addActionButtons(children, 'general', actions=(ACTIONS[1],))
    return group


def _applyTypeVisibility(inputs, is_grip):
    """Only the chosen family's parameters stay on screen."""
    heat = inputs.itemById('heatInsertGroup')
    if heat:
        heat.isVisible = not is_grip
    for input_id in GRIP_ONLY_INPUTS:
        item = inputs.itemById(input_id)
        if item:
            item.isVisible = is_grip


def _writeGripSpec(inputs, spec):
    for index, input_id in enumerate(tm_config.GRIP_RIDGE_INPUTS):
        _setValue(inputs, input_id, spec[index])


def _writeSettings(inputs, values, which):
    for input_id, (key, _section) in which.items():
        if key in values:
            _setValue(inputs, input_id, values[key])


def _loadGripSpec(inputs, insert_name):
    """Show one grip insert's stored parameters, and reveal the right group."""
    _applyTypeVisibility(inputs, insert_name in tm_state.GRIP_RIDGE_INSERTS)
    spec = tm_state.GRIP_RIDGE_INSERTS.get(insert_name)
    if spec:
        _writeGripSpec(inputs, spec)


def _runAction(inputs, prefix, pressed_label):
    """Carry out one action button. Only Save writes config.ini."""
    suffix = next((s for label, _icon, s in ACTIONS if label == pressed_label), None)
    if suffix is None:
        return
    action_id = prefix + suffix
    insertName = _selectedName(inputs.itemById('insertSize'))

    if action_id == 'heatRestoreDefaults':
        _writeSettings(inputs, tm_state.DEFAULT_CONFIG, tm_config.HEAT_INSERT_INPUTS)
        _setValue(inputs, 'addChamfer',
                  tm_state.DEFAULT_CONFIG['chamfer_enabled_default'])
        _setValue(inputs, 'addBottomRadius',
                  tm_state.DEFAULT_CONFIG['bottom_radius_enabled_default'])

    elif action_id == 'heatRestoreSaved':
        _writeSettings(inputs, tm_config.saved_settings(), tm_config.HEAT_INSERT_INPUTS)

    elif action_id == 'heatSave':
        tm_config.save_settings(tm_config.read_settings_inputs(inputs))
        tm_config.save_checkbox_states(
            _valueOf(inputs, 'addChamfer', True),
            _valueOf(inputs, 'addBottomRadius', False),
            _valueOf(inputs, 'setShowMessage', True),
            tm_state.CONFIG.get('hole_type_blind', True))

    elif action_id == 'gripRestoreDefaults':
        spec = tm_config.default_grip_spec(insertName)
        if spec:
            _writeGripSpec(inputs, spec)
        _writeSettings(inputs, tm_state.DEFAULT_CONFIG, tm_config.GRIP_GLOBAL_INPUTS)

    elif action_id == 'gripRestoreSaved':
        spec = tm_config.saved_grip_spec(insertName)
        if spec:
            _writeGripSpec(inputs, spec)
        _writeSettings(inputs, tm_config.saved_settings(),
                       tm_config.GRIP_GLOBAL_INPUTS)

    elif action_id == 'gripSave':
        if insertName in tm_state.GRIP_RIDGE_INSERTS:
            spec = tm_config.read_grip_inputs(inputs, insertName)
            tm_state.GRIP_RIDGE_INSERTS[insertName] = spec
            tm_config.save_grip_ridge_insert(insertName, spec)
        tm_config.save_settings(tm_config.read_settings_inputs(inputs))

    elif action_id == 'generalSave':
        tm_config.save_settings(tm_config.read_settings_inputs(inputs))


def updateInfoText(inputs):
    """Refresh the info text box with specs for the currently selected insert."""
    try:
        insertSize = inputs.itemById('insertSize')
        holeType = inputs.itemById('holeType')
        infoText = inputs.itemById('infoText')

        insertName = insertSize.selectedItem.name
        isBlindHole = holeType.selectedItem.name == 'Blind Hole'

        # Live values from the Settings group (CONFIG values until it is built)
        settings = tm_config.read_settings_inputs(inputs)

        is_grip_ridge = insertName in tm_state.GRIP_RIDGE_INSERTS
        if not is_grip_ridge and insertName not in tm_state.INSERT_SPECS:
            infoText.formattedText = f'<b>{insertName}</b><br/>No specification found in config.ini.'
            return

        if is_grip_ridge:
            # Live values from the Grip Ridge group (stored spec until it is built)
            (clearanceDia, holeDepth, gripChamferSize,
             gripRidgeDia, gripArcDistance, gripCount) = tm_config.read_grip_inputs(
                inputs, insertName)
            holeDia = clearanceDia
            totalDepth = holeDepth
        else:
            holeDia, insertLen, minWall = tm_state.INSERT_SPECS[insertName]

        addChamfer = inputs.itemById('addChamfer')
        chamferOn = addChamfer.value if addChamfer else False

        if is_grip_ridge:
            depthStr = f'{totalDepth:.1f} mm' if isBlindHole else 'Through body'
        elif isBlindHole:
            extra = settings['blind_hole_extra_depth']
            chamferSize = settings['chamfer_size']
            chamfer = chamferSize if chamferOn else 0.0
            holeDepth = calc_blind_hole_depth_mm(insertLen, extra, chamfer)
            if chamferOn:
                depthStr = f'{holeDepth:.1f} mm ({insertLen} + {extra} + {chamferSize})'
            else:
                depthStr = f'{holeDepth:.1f} mm ({insertLen} + {extra})'
        else:
            depthStr = 'Through body'

        if is_grip_ridge:
            grip_chamfer_angle = settings['grip_chamfer_angle']
            chamfer_info = f'{gripChamferSize}mm @ {grip_chamfer_angle}°' if chamferOn else 'Off'
            info = (f'<b>{insertName}</b><br/>' +
                    f'Hole: {holeDia:.1f} mm  ·  Depth: {totalDepth:.1f} mm<br/>' +
                    f'Ridges: {gripCount}× Ø{gripRidgeDia:.1f} mm at {gripArcDistance:.2f} mm<br/>' +
                    f'Chamfer: {chamfer_info}<br/>' +
                    f'Hole depth: {depthStr}')
            warning = tm_helpers.grip_ridge_warning(
                clearanceDia, gripRidgeDia, gripArcDistance, gripCount)
            if warning:
                info += f'<br/><b>Warning:</b> {warning}'
        else:
            info = (f'<b>{insertName}</b><br/>' +
                    f'Hole: {holeDia} mm  ·  Depth: {insertLen} mm<br/>' +
                    f'Hole depth: {depthStr}<br/>' +
                    f'Min wall: {minWall} mm')

        infoText.formattedText = info

    except Exception:
        tm_helpers.log('updateInfoText failed: {}'.format(traceback.format_exc()))
