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
            tm_state._handlers.append(onExecute)

            onInputChanged = InputChangedHandler()
            cmd.inputChanged.add(onInputChanged)
            tm_state._handlers.append(onInputChanged)

            onValidateInputs = ValidateInputsHandler()
            cmd.validateInputs.add(onValidateInputs)
            tm_state._handlers.append(onValidateInputs)

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

            # Hole type
            holeTypeGroup = inputs.addRadioButtonGroupCommandInput('holeType', 'Hole Type')
            saved_is_blind = tm_state.CONFIG.get('hole_type_blind', True)
            holeTypeGroup.listItems.add('Blind Hole', saved_is_blind)
            holeTypeGroup.listItems.add('Through Hole', not saved_is_blind)

            # Grip-edge depth override (hidden unless a grip-ridge insert is selected)
            # Default value is the FULL calculated hole depth (insert + extra + chamfer)
            # so the user sees and controls the actual hole depth directly.
            _, configInsertLen, _, _, _ = tm_state.GRIP_RIDGE_INSERTS.get(
                lastSelected, (0, 7.0, 0, 0, 0))
            isGripDefault = lastSelected in tm_state.GRIP_RIDGE_INSERTS
            defaultTotalDepth = (configInsertLen
                                 + tm_state.CONFIG['blind_hole_extra_depth']
                                 + tm_state.CONFIG['chamfer_size'])
            inputs.addFloatSpinnerCommandInput(
                'gripEdgeDepth', 'Hole Depth (mm)', 'mm', 0.1, 100.0, defaultTotalDepth, 1)
            depthInput = inputs.itemById('gripEdgeDepth')
            depthInput.isVisible = isGripDefault

            # Chamfer option
            inputs.addBoolValueInput('addChamfer',
                                     'Add Chamfer',
                                     True, '',
                                     tm_state.CONFIG['chamfer_enabled_default'])

            # Bottom radius option
            inputs.addBoolValueInput('addBottomRadius',
                                     f'Add Bottom Fillet ({tm_state.CONFIG["bottom_radius_size"]}mm)',
                                     True, '',
                                     tm_state.CONFIG['bottom_radius_enabled_default'])

            # Info text
            inputs.addTextBoxCommandInput('infoText', '', '', 5, True)
            updateInfoText(inputs)

            # Developer: debug export (only visible when enabled in config.ini)
            if tm_state.CONFIG.get('enable_debug_export', False):
                inputs.addBoolValueInput('exportDebug',
                                         'Export Debug JSON (saves fixture to debug_exports/)',
                                         True, '',
                                         False)

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

            # Show/hide grip-edge depth spinner based on insert type
            if changedInput.id == 'insertSize':
                insertSize = inputs.itemById('insertSize')
                depthInput = inputs.itemById('gripEdgeDepth')
                insertName = insertSize.selectedItem.name
                isGrip = insertName in tm_state.GRIP_RIDGE_INSERTS
                if depthInput:
                    depthInput.isVisible = isGrip
                    if isGrip:
                        _, configInsertLen, _, _, _ = tm_state.GRIP_RIDGE_INSERTS[insertName]
                        totalDepth = (configInsertLen
                                      + tm_state.CONFIG['blind_hole_extra_depth']
                                      + tm_state.CONFIG['chamfer_size'])
                        depthInput.value = totalDepth

            if changedInput.id in ('insertSize', 'holeType', 'addChamfer', 'gripEdgeDepth'):
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


def updateInfoText(inputs):
    """Refresh the info text box with specs for the currently selected insert."""
    try:
        insertSize = inputs.itemById('insertSize')
        holeType = inputs.itemById('holeType')
        infoText = inputs.itemById('infoText')

        insertName = insertSize.selectedItem.name
        isBlindHole = holeType.selectedItem.name == 'Blind Hole'

        is_grip_ridge = insertName in tm_state.GRIP_RIDGE_INSERTS

        if is_grip_ridge:
            clearanceDia, configInsertLen, minWall, nominalDia, gripEdgeChamfer = tm_state.GRIP_RIDGE_INSERTS[insertName]
            holeDia = clearanceDia
            arc_dia = 0.5 * nominalDia

            # Use spinner value if visible (it's stored in cm internally),
            # otherwise fall back to the calculated default in mm
            depthInput = inputs.itemById('gripEdgeDepth')
            if depthInput and depthInput.isVisible:
                totalDepth = depthInput.value * 10.0
            else:
                totalDepth = (configInsertLen
                              + tm_state.CONFIG['blind_hole_extra_depth']
                              + tm_state.CONFIG['chamfer_size'])
        else:
            holeDia, insertLen, minWall = tm_state.INSERT_SPECS[insertName]

        addChamfer = inputs.itemById('addChamfer')
        chamferOn = addChamfer.value if addChamfer else False

        if is_grip_ridge:
            depthStr = f'{totalDepth:.1f} mm' if isBlindHole else 'Through body'
        elif isBlindHole:
            extra = tm_state.CONFIG['blind_hole_extra_depth']
            chamfer = tm_state.CONFIG['chamfer_size'] if chamferOn else 0.0
            holeDepth = calc_blind_hole_depth_mm(insertLen, extra, chamfer)
            if chamferOn:
                depthStr = f'{holeDepth:.1f} mm ({insertLen} + {extra} + {tm_state.CONFIG["chamfer_size"]})'
            else:
                depthStr = f'{holeDepth:.1f} mm ({insertLen} + {extra})'
        else:
            depthStr = 'Through body'

        if is_grip_ridge:
            grip_chamfer_angle = tm_state.CONFIG.get('grip_chamfer_angle', 60)
            chamfer_info = f'{tm_state.CONFIG["chamfer_size"]}mm @ {grip_chamfer_angle}°' if chamferOn else 'Off'
            info = (f'<b>{insertName}</b><br/>' +
                    f'Hole: {holeDia:.1f} mm  ·  Depth: {totalDepth:.1f} mm<br/>' +
                    f'Ridges: 3× Ø{arc_dia:.1f} mm  ·  Grip chamfer: {gripEdgeChamfer} mm<br/>' +
                    f'Chamfer: {chamfer_info}<br/>' +
                    f'Hole depth: {depthStr}<br/>' +
                    f'Min wall: {minWall} mm')
        else:
            info = (f'<b>{insertName}</b><br/>' +
                    f'Hole: {holeDia} mm  ·  Depth: {insertLen} mm<br/>' +
                    f'Hole depth: {depthStr}<br/>' +
                    f'Min wall: {minWall} mm')

        infoText.formattedText = info

    except Exception:
        tm_helpers.log('updateInfoText failed: {}'.format(traceback.format_exc()))
