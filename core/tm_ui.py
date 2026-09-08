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


class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            # Reload config to pick up any saved changes
            tm_config.load_config()

            cmd = args.command
            
            # Set dialog size to properly display all labels and options
            cmd.setDialogMinimumSize(350, 600)

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
            inputs.addSelectionInput('bodySelect', 'Target Body',
                                     'Select the solid body to cut into')
            # The selection filter and limits are set below after creation
            bodySelect = inputs.itemById('bodySelect')
            bodySelect.addSelectionFilter('SolidBodies')
            bodySelect.setSelectionLimits(1, 1)

            # Sketch point selection
            inputs.addSelectionInput('pointSelect', 'Sketch Point(s)',
                                     'Select sketch point(s) where holes will be created')
            pointSelect = inputs.itemById('pointSelect')
            pointSelect.addSelectionFilter('SketchPoints')
            pointSelect.setSelectionLimits(1, 0)

            # Insert size dropdown
            inputs.addDropDownCommandInput('insertSize', 'Insert Size',
                                           adsk.core.DropDownStyles.TextListDropDownStyle)
            insertDropdown = inputs.itemById('insertSize')
            insertList = insertDropdown.listItems

            lastSelected = tm_state.CONFIG.get('last_selected_insert', 'M3 x 5.7mm (standard)')
            foundLastSelected = False

            for name in tm_state.INSERT_SPECS.keys():
                isSelected = (name == lastSelected)
                if isSelected:
                    foundLastSelected = True
                insertList.add(name, isSelected)

            for name in tm_state.GRIP_RIDGE_INSERTS.keys():
                isSelected = (name == lastSelected)
                if isSelected:
                    foundLastSelected = True
                insertList.add(name, isSelected)

            if not foundLastSelected and insertList.count > 0:
                insertList.item(0).isSelected = True
                lastSelected = insertList.item(0).name

            # Hole type
            holeTypeGroup = inputs.addRadioButtonGroupCommandInput('holeType', 'Hole Type')
            saved_is_blind = tm_state.CONFIG.get('hole_type_blind', True)
            holeTypeGroup.listItems.add('Blind Hole', saved_is_blind)
            holeTypeGroup.listItems.add('Through Hole', not saved_is_blind)

            # Grip ridge parameters (only shown while a Grip insert is selected)
            _addGripRidgeGroup(inputs, lastSelected)

            # Chamfer option
            inputs.addBoolValueInput('addChamfer',
                                     'Add Chamfer',
                                     True, '',
                                     tm_state.CONFIG['chamfer_enabled_default'])

            # Bottom radius option
            inputs.addBoolValueInput('addBottomRadius',
                                     'Add Bottom Fillet',
                                     True, '',
                                     tm_state.CONFIG['bottom_radius_enabled_default'])

            # Info text
            inputs.addTextBoxCommandInput('infoText', '', '', 5, True)

            # Settings: edit the config.ini design parameters without leaving
            # Fusion. Collapsed by default; applied to this run and saved on OK.
            _addSettingsGroup(inputs)

            # Developer: debug export (only visible when enabled in config.ini)
            if tm_state.CONFIG.get('enable_debug_export', False):
                inputs.addBoolValueInput('exportDebug',
                                         'Export Debug JSON (saves fixture to debug_exports/)',
                                         True, '',
                                         False)

            # Last, so the info text reflects the Settings group's values
            updateInfoText(inputs)

        except Exception:
            tm_state._ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


class InputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            inputs = args.inputs
            changedInput = args.input

            # Auto-focus on point selection after body is selected
            if changedInput.id == 'bodySelect':
                bodySelect = inputs.itemById('bodySelect')
                if bodySelect.selectionCount > 0:
                    pointSelect = inputs.itemById('pointSelect')
                    pointSelect.isEnabled = True
                    pointSelect.hasFocus = True

            # Show the grip ridge group and reload it for the chosen insert
            if changedInput.id == 'insertSize':
                insertName = inputs.itemById('insertSize').selectedItem.name
                isGrip = insertName in tm_state.GRIP_RIDGE_INSERTS
                group = inputs.itemById('gripRidgeGroup')
                if group:
                    group.isVisible = isGrip
                if isGrip:
                    spec = tm_state.GRIP_RIDGE_INSERTS[insertName]
                    for index, input_id in enumerate(tm_config.GRIP_RIDGE_INPUTS):
                        _setValue(inputs, input_id, spec[index])

            # Restore Defaults acts as a button: reset the group, untick, and
            # let the user see the result before committing with OK.
            if changedInput.id == 'setRestoreDefaults' and changedInput.value:
                for input_id, (key, _section) in tm_config.SETTINGS_INPUTS.items():
                    _setValue(inputs, input_id, tm_state.DEFAULT_CONFIG[key])
                changedInput.value = False

            if changedInput.id == 'gripRestoreDefaults' and changedInput.value:
                insertName = inputs.itemById('insertSize').selectedItem.name
                spec = tm_config.default_grip_spec(insertName)
                if spec:
                    for index, input_id in enumerate(tm_config.GRIP_RIDGE_INPUTS):
                        _setValue(inputs, input_id, spec[index])
                changedInput.value = False

            if changedInput.id in (('insertSize', 'holeType', 'addChamfer',
                                    'setChamferSize', 'setExtraDepth', 'setGripChamferAngle',
                                    'setRestoreDefaults', 'gripRestoreDefaults')
                                   + tm_config.GRIP_RIDGE_INPUTS):
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


def _addGripRidgeGroup(inputs, insert_name):
    """Add the per-insert Grip Ridge parameters from [GripRidgeInserts].

    Only visible while a Grip insert is selected. Unitless spinners, mm as
    labelled; min/max mirror the validation in tm_config.load_config().
    """
    spec = tm_state.GRIP_RIDGE_INSERTS.get(insert_name)
    if spec is None:
        # Hidden anyway, but the inputs still need starting values
        spec = next(iter(tm_state.GRIP_RIDGE_INSERTS.values()), (3.2, 7, 0.28, 1.5, 2.05, 3))
    clearance, depth, chamfer, ridge_dia, arc_distance, count = spec

    group = inputs.addGroupCommandInput('gripRidgeGroup', 'Grip Ridge Parameters')
    children = group.children

    children.addFloatSpinnerCommandInput(
        'gripClearanceDia', 'Clearance Diameter (mm)', '', 0.1, 50.0, 0.1, clearance)
    children.addFloatSpinnerCommandInput(
        'gripEdgeDepth', 'Hole Depth (mm)', '', 0.1, 100.0, 0.5, depth)
    children.addFloatSpinnerCommandInput(
        'gripEdgeChamfer', 'Ridge Chamfer (mm)', '', 0.0, 5.0, 0.05, chamfer)
    children.addFloatSpinnerCommandInput(
        'gripRidgeDia', 'Ridge Diameter (mm)', '', 0.1, 20.0, 0.1, ridge_dia)
    children.addFloatSpinnerCommandInput(
        'gripArcDistance', 'Ridge Distance from Centre (mm)', '', 0.1, 50.0, 0.05, arc_distance)
    children.addIntegerSpinnerCommandInput(
        'gripCount', 'Number of Ridges', 1, 12, 1, int(count))
    children.addBoolValueInput(
        'gripRestoreDefaults', 'Restore Defaults', True, '', False)

    group.isVisible = insert_name in tm_state.GRIP_RIDGE_INSERTS
    return group


def _addSettingsGroup(inputs):
    """Add the collapsed Settings group that edits config.ini design parameters.

    These spinners are unitless on purpose: `.value` is the number shown, in mm
    or degrees, with no Fusion-internal cm/radian conversion to get wrong. The
    grip depth spinner above is the exception and is declared in 'mm'.

    Min/max mirror the validation in tm_config.load_config().
    """
    group = inputs.addGroupCommandInput('settingsGroup', 'Settings')
    group.isExpanded = False
    children = group.children

    children.addFloatSpinnerCommandInput(
        'setChamferSize', 'Chamfer Size (mm)', '',
        0.1, 5.0, 0.1, tm_state.CONFIG['chamfer_size'])
    children.addFloatSpinnerCommandInput(
        'setExtraDepth', 'Blind Hole Extra Depth (mm)', '',
        0.0, 10.0, 0.1, tm_state.CONFIG['blind_hole_extra_depth'])
    children.addFloatSpinnerCommandInput(
        'setBottomRadius', 'Bottom Fillet Radius (mm)', '',
        0.0, 5.0, 0.1, tm_state.CONFIG['bottom_radius_size'])
    children.addFloatSpinnerCommandInput(
        'setGripChamferAngle', 'Grip Chamfer Angle (deg)', '',
        15.0, 85.0, 1.0, tm_state.CONFIG['grip_chamfer_angle'])
    children.addBoolValueInput(
        'setShowMessage', 'Show Success Message', True, '',
        tm_state.CONFIG.get('show_success_message', True))
    children.addBoolValueInput(
        'setEnableLogging', 'Enable Logging', True, '',
        tm_state.CONFIG.get('enable_logging', False))
    children.addBoolValueInput(
        'setRestoreDefaults', 'Restore Defaults', True, '', False)

    return group


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
