"""
tm_config.py – Configuration loading, validation, saving, and defaults.

Reads/writes config.ini. Mutates INSERT_SPECS and CONFIG in tm_state.

Config sections:
  [Settings]         - Design parameters (chamfer_size, blind_hole_extra_depth, bottom_radius_size)
  [Inserts]          - Insert specifications (name = diameter, length, min_wall)
  [GripRidgeInserts] - Grip-ridge insert specs (name = clearance_dia, depth, min_wall, nominal_dia, [optional] grip_edge_chamfer)
  [UI State]         - Remembered menu state (chamfer_enabled_default, bottom_radius_enabled_default, etc.)
  [Developer]        - Debug flags (enable_logging, enable_debug_export)
"""
import io
import os
import configparser
import tm_helpers
import tm_state


def _get_config_path():
    """Return the absolute path to config.ini."""
    addon_path = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    return os.path.join(addon_path, 'config.ini')


def _read_config_file(config_file=None):
    """Read and return a RawConfigParser from config.ini."""
    if config_file is None:
        config_file = _get_config_path()
    config = configparser.RawConfigParser()
    config.optionxform = str  # Preserve case
    config.read(config_file, encoding='utf-8')
    return config


def _is_old_format(config):
    """Check if config uses old single-section format (no [UI State] section)."""
    return not config.has_section('UI State')


def _get(config, key, section_new, fallback, getter='get'):
    """Read a key from the correct section, falling back to [Settings] for old format."""
    for section in (section_new, 'Settings'):
        if config.has_section(section) and config.has_option(section, key):
            try:
                if getter == 'float':
                    return config.getfloat(section, key)
                elif getter == 'boolean':
                    return config.getboolean(section, key)
                else:
                    return config.get(section, key)
            except (ValueError, configparser.Error):
                return fallback
    return fallback


def load_config(config_file=None):
    """Load configuration from config.ini with validation. Creates defaults if missing."""
    if config_file is None:
        config_file = _get_config_path()

    if not os.path.exists(config_file):
        create_default_config(config_file)

    errors = []
    warnings = []
    defaults = tm_state.DEFAULT_CONFIG

    try:
        config = _read_config_file(config_file)
        needs_migration = _is_old_format(config)

        # --- [Settings]: Design parameters ---
        chamfer = _get(config, 'chamfer_size', 'Settings', defaults['chamfer_size'], 'float')
        if chamfer <= 0 or chamfer > 5.0:
            warnings.append(f'Chamfer size {chamfer}mm is unusual (expected 0-5mm). '
                            f'Using default {defaults["chamfer_size"]}mm.')
            chamfer = defaults['chamfer_size']
        tm_state.CONFIG['chamfer_size'] = chamfer

        extra_depth = _get(config, 'blind_hole_extra_depth', 'Settings',
                           defaults['blind_hole_extra_depth'], 'float')
        if extra_depth < 0 or extra_depth > 10.0:
            warnings.append(f'Extra depth {extra_depth}mm is unusual (expected 0-10mm). '
                            f'Using default {defaults["blind_hole_extra_depth"]}mm.')
            extra_depth = defaults['blind_hole_extra_depth']
        tm_state.CONFIG['blind_hole_extra_depth'] = extra_depth

        bottom_radius = _get(config, 'bottom_radius_size', 'Settings',
                             defaults['bottom_radius_size'], 'float')
        if bottom_radius < 0 or bottom_radius > 5.0:
            warnings.append(f'Bottom radius {bottom_radius}mm is unusual (expected 0-5mm). '
                            f'Using default {defaults["bottom_radius_size"]}mm.')
            bottom_radius = defaults['bottom_radius_size']
        tm_state.CONFIG['bottom_radius_size'] = bottom_radius

        # --- [UI State]: Remembered menu state ---
        for key in ('chamfer_enabled_default', 'bottom_radius_enabled_default',
                    'show_success_message', 'hole_type_blind'):
            tm_state.CONFIG[key] = _get(config, key, 'UI State', defaults[key], 'boolean')
        tm_state.CONFIG['last_selected_insert'] = _get(
            config, 'last_selected_insert', 'UI State', defaults['last_selected_insert'])

        # --- [Developer]: Debug flags ---
        for key in ('enable_logging', 'enable_debug_export'):
            tm_state.CONFIG[key] = _get(config, key, 'Developer', defaults[key], 'boolean')

        # --- Grip-ridge chamfer angle ---
        grip_chamfer_angle = _get(config, 'grip_chamfer_angle', 'Settings',
                                  defaults['grip_chamfer_angle'], 'float')
        if grip_chamfer_angle < 15 or grip_chamfer_angle > 85:
            warnings.append(f'Grip chamfer angle {grip_chamfer_angle}° is unusual '
                            f'(expected 15-85°). Using default '
                            f'{defaults["grip_chamfer_angle"]}°.')
            grip_chamfer_angle = defaults['grip_chamfer_angle']
        tm_state.CONFIG['grip_chamfer_angle'] = grip_chamfer_angle

        # --- [Inserts] ---
        tm_state.INSERT_SPECS.clear()
        if config.has_section('Inserts'):
            for name in config.options('Inserts'):
                if name.startswith('#'):
                    continue
                try:
                    values = config.get('Inserts', name)
                    if not values.strip() or values.strip().startswith('#'):
                        continue
                    parts = [x.strip() for x in values.split(',')]
                    if len(parts) != 3:
                        warnings.append(f'Insert "{name}" has {len(parts)} values (expected 3). Skipped.')
                        continue
                    try:
                        hole_dia = float(parts[0])
                        insert_len = float(parts[1])
                        min_wall = float(parts[2])
                        if hole_dia <= 0 or hole_dia > 50:
                            warnings.append(f'Insert "{name}": hole diameter {hole_dia}mm is invalid. Skipped.')
                            continue
                        if insert_len <= 0 or insert_len > 100:
                            warnings.append(f'Insert "{name}": insert length {insert_len}mm is invalid. Skipped.')
                            continue
                        if min_wall < 0 or min_wall > 20:
                            warnings.append(f'Insert "{name}": min wall {min_wall}mm is invalid. Skipped.')
                            continue
                        tm_state.INSERT_SPECS[name] = (hole_dia, insert_len, min_wall)
                    except ValueError:
                        warnings.append(f'Insert "{name}": Invalid number format. Skipped.')
                        continue
                except Exception:
                    warnings.append(f'Insert "{name}": Error reading values. Skipped.')
                    continue

        if not tm_state.INSERT_SPECS:
            errors.append('No valid inserts found in config.ini!')
            tm_state.INSERT_SPECS.update(get_default_inserts())
            warnings.append('Using default CNC Kitchen specifications.')

        # --- [GripRidgeInserts] ---
        tm_state.GRIP_RIDGE_INSERTS.clear()
        if config.has_section('GripRidgeInserts'):
            for name in config.options('GripRidgeInserts'):
                if name.startswith('#'):
                    continue
                try:
                    values = config.get('GripRidgeInserts', name)
                    if not values.strip() or values.strip().startswith('#'):
                        continue
                    parts = [x.strip() for x in values.split(',')]
                    if len(parts) != 6:
                        warnings.append(
                            f'Grip-ridge insert "{name}" has {len(parts)} values (expected 6). Skipped.')
                        continue
                    try:
                        clearance_dia = float(parts[0])
                        hole_depth = float(parts[1])
                        grip_edge_chamfer = float(parts[2])
                        grip_ridge_dia = float(parts[3])
                        grip_arc_distance = float(parts[4])
                        grip_count = int(parts[5])
                        if clearance_dia <= 0 or clearance_dia > 50:
                            warnings.append(
                                f'Grip-ridge insert "{name}": clearance diameter '
                                f'{clearance_dia}mm is invalid. Skipped.')
                            continue
                        if hole_depth <= 0 or hole_depth > 100:
                            warnings.append(
                                f'Grip-ridge insert "{name}": hole depth {hole_depth}mm is invalid. Skipped.')
                            continue
                        if grip_edge_chamfer < 0 or grip_edge_chamfer > 5.0:
                            warnings.append(
                                f'Grip-ridge insert "{name}": grip edge chamfer '
                                f'{grip_edge_chamfer}mm is invalid. Using default 0.2mm.')
                            grip_edge_chamfer = 0.2
                        if grip_ridge_dia <= 0 or grip_ridge_dia > 20:
                            warnings.append(
                                f'Grip-ridge insert "{name}": grip ridge diameter '
                                f'{grip_ridge_dia}mm is invalid. Skipped.')
                            continue
                        if grip_arc_distance <= 0 or grip_arc_distance > 50:
                            warnings.append(
                                f'Grip-ridge insert "{name}": grip arc distance '
                                f'{grip_arc_distance}mm is invalid. Skipped.')
                            continue
                        if grip_count < 1 or grip_count > 12:
                            warnings.append(
                                f'Grip-ridge insert "{name}": grip count '
                                f'{grip_count} invalid. Using default 3.')
                            grip_count = 3
                        tm_state.GRIP_RIDGE_INSERTS[name] = (
                            clearance_dia, hole_depth, grip_edge_chamfer,
                            grip_ridge_dia, grip_arc_distance, grip_count)
                    except ValueError:
                        warnings.append(
                            f'Grip-ridge insert "{name}": Invalid number format. Skipped.')
                        continue
                except Exception:
                    warnings.append(
                        f'Grip-ridge insert "{name}": Error reading values. Skipped.')
                    continue

        if not tm_state.GRIP_RIDGE_INSERTS:
            tm_state.GRIP_RIDGE_INSERTS.update(get_default_grip_ridge_inserts())

        # Auto-migrate old format to new sections
        if needs_migration:
            _migrate_config(config_file)

        if errors or warnings:
            msg = ''
            if errors:
                msg += 'ERRORS:\n' + '\n'.join(errors) + '\n\n'
            if warnings:
                msg += 'WARNINGS:\n' + '\n'.join(warnings)
            if tm_state._ui:
                tm_state._ui.messageBox(f'Config.ini issues:\n\n{msg}')

    except Exception as e:
        tm_helpers.log(f'Error loading config.ini: {str(e)}')
        if tm_state._ui:
            tm_state._ui.messageBox(f'Error loading config.ini: {str(e)}\nUsing default specifications.')
        tm_state.INSERT_SPECS.update(get_default_inserts())

    return tm_state.INSERT_SPECS, tm_state.CONFIG


def _migrate_config(config_file=None):
    """Rewrite config.ini from old single-section format to new multi-section format."""
    try:
        _write_config_file(config_file)
    except Exception as e:
        tm_helpers.log(f'Config migration failed: {e}')  # Migration failure is non-critical; old format still works


def _write_config_file(config_file=None):
    """Write current CONFIG and INSERT_SPECS to config.ini in the new multi-section format."""
    if config_file is None:
        config_file = _get_config_path()

    config = configparser.RawConfigParser()
    config.optionxform = str

    # [Settings]
    config.add_section('Settings')
    config.set('Settings', 'chamfer_size', str(tm_state.CONFIG.get('chamfer_size', 0.5)))
    config.set('Settings', 'blind_hole_extra_depth', str(tm_state.CONFIG.get('blind_hole_extra_depth', 1.0)))
    config.set('Settings', 'bottom_radius_size', str(tm_state.CONFIG.get('bottom_radius_size', 0.5)))
    config.set('Settings', 'grip_chamfer_angle', str(tm_state.CONFIG.get('grip_chamfer_angle', 78)))

    # [Inserts]
    config.add_section('Inserts')
    for name, (dia, length, wall) in tm_state.INSERT_SPECS.items():
        config.set('Inserts', name, f'{dia}, {length}, {wall}')

    # [GripRidgeInserts]
    config.add_section('GripRidgeInserts')
    for name, (clearance_dia, hole_depth, grip_edge_chamfer,
               grip_ridge_dia, grip_arc_distance, grip_count) in tm_state.GRIP_RIDGE_INSERTS.items():
        config.set('GripRidgeInserts', name,
                   f'{clearance_dia}, {hole_depth}, {grip_edge_chamfer}, '
                   f'{grip_ridge_dia}, {grip_arc_distance}, {grip_count}')

    # [UI State]
    config.add_section('UI State')
    config.set('UI State', 'chamfer_enabled_default', str(tm_state.CONFIG.get('chamfer_enabled_default', True)))
    config.set('UI State', 'bottom_radius_enabled_default', str(tm_state.CONFIG.get('bottom_radius_enabled_default', False)))
    config.set('UI State', 'show_success_message', str(tm_state.CONFIG.get('show_success_message', True)))
    config.set('UI State', 'hole_type_blind', str(tm_state.CONFIG.get('hole_type_blind', True)))
    config.set('UI State', 'last_selected_insert', tm_state.CONFIG.get('last_selected_insert', 'M3 x 5.7mm (standard)'))

    # [Developer]
    config.add_section('Developer')
    config.set('Developer', 'enable_logging', str(tm_state.CONFIG.get('enable_logging', False)))
    config.set('Developer', 'enable_debug_export', str(tm_state.CONFIG.get('enable_debug_export', False)))

    with open(config_file, 'w', encoding='utf-8') as f:
        config.write(f)


def _is_section_header(line):
    """True if a config.ini line is a [Section] header."""
    stripped = line.strip()
    return stripped.startswith('[') and stripped.endswith(']')


def save_values(updates, config_file=None):
    """Merge {section: {key: value}} into config.ini, rewriting only those lines.

    Deliberately not a configparser round-trip: that rebuilds the whole file and
    drops every comment in it, including the format hint above [GripRidgeInserts].
    Editing the matching lines in place keeps comments, ordering and spacing, and
    leaves the insert tables alone.

    Old-format files have no [UI State] and keep those keys in [Settings].

    Returns:
        True if the file was written.
    """
    try:
        if config_file is None:
            config_file = _get_config_path()

        try:
            with io.open(config_file, 'r', encoding='utf-8') as f:
                lines = f.read().split('\n')
        except OSError:
            lines = []

        sections_present = {line.strip()[1:-1] for line in lines if _is_section_header(line)}

        pending = {}
        for section, values in updates.items():
            if section == 'UI State' and 'UI State' not in sections_present:
                section = 'Settings'
            pending.setdefault(section, {}).update(values)

        # Pass 1: overwrite the keys that are already in the file
        out = []
        section = None
        for line in lines:
            stripped = line.strip()
            if _is_section_header(line):
                section = stripped[1:-1]
            elif (section in pending and '=' in stripped
                    and not stripped.startswith(('#', ';'))):
                key = stripped.split('=', 1)[0].strip()
                if key in pending[section]:
                    line = f'{key} = {pending[section].pop(key)}'
            out.append(line)

        # Pass 2: add the keys that were not there, under their own section
        for section, leftovers in pending.items():
            if not leftovers:
                continue
            new_lines = [f'{key} = {value}' for key, value in leftovers.items()]
            header = next((i for i, line in enumerate(out)
                           if _is_section_header(line) and line.strip()[1:-1] == section), None)
            if header is None:
                if out and out[-1].strip():
                    out.append('')
                out.append(f'[{section}]')
                out.extend(new_lines)
                out.append('')
            else:
                out[header + 1:header + 1] = new_lines

        with io.open(config_file, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(out))
        return True
    except Exception as e:
        tm_helpers.log(f'Failed to save config values: {e}')
        return False


def save_last_selected_insert(insert_name, config_file=None):
    """Persist the last selected insert name to config.ini."""
    return save_values({'UI State': {'last_selected_insert': insert_name}}, config_file)


HOLE_TYPE_LABELS = ('Blind Hole', 'Through Hole')


def read_hole_type(inputs):
    """True for a blind hole, read off the dialog's radio group.

    The control is the source of truth. CONFIG is only the fallback for callers
    that run before the dialog is built, and the remembered choice the next one
    opens on.
    """
    group = inputs.itemById('holeType')
    if group and group.selectedItem:
        return group.selectedItem.name == HOLE_TYPE_LABELS[0]
    return tm_state.CONFIG.get('hole_type_blind', True)


def save_checkbox_states(chamfer_state, radius_state, show_message_state, is_blind_hole, config_file=None):
    """Persist UI checkbox states and hole type to config.ini."""
    return save_values({'UI State': {
        'chamfer_enabled_default': chamfer_state,
        'bottom_radius_enabled_default': radius_state,
        'show_success_message': show_message_state,
        'hole_type_blind': is_blind_hole,
    }}, config_file)


# Design parameters the dialog can edit:
#   command input id -> (CONFIG key, config.ini section)
# Split by the group each one is shown in, so a group's Restore Defaults resets
# only its own inputs. The spinner ranges in tm_ui match the validation in
# load_config(), so a value entered here can never be one the next load rejects.

# Shown in Heat Insert Parameters
HEAT_INSERT_INPUTS = {
    'setChamferSize': ('chamfer_size', 'Settings'),
    'setExtraDepth': ('blind_hole_extra_depth', 'Settings'),
    'setBottomRadius': ('bottom_radius_size', 'Settings'),
}

# Shown in Grip Ridge Parameters. Global rather than per-insert, unlike the
# GRIP_RIDGE_INPUTS spec values, but it belongs beside them.
GRIP_GLOBAL_INPUTS = {
    'setGripChamferAngle': ('grip_chamfer_angle', 'Settings'),
}

# Shown in General, and relevant whichever insert type is chosen
GENERAL_INPUTS = {
    'setShowMessage': ('show_success_message', 'UI State'),
    'setEnableLogging': ('enable_logging', 'Developer'),
}

SETTINGS_INPUTS = {**HEAT_INSERT_INPUTS, **GRIP_GLOBAL_INPUTS, **GENERAL_INPUTS}


# Per-insert grip ridge parameters the dialog can edit. Order matches the
# GRIP_RIDGE_INSERTS spec tuple, so index here == index there.
GRIP_RIDGE_INPUTS = (
    'gripClearanceDia',
    'gripEdgeDepth',
    'gripEdgeChamfer',
    'gripRidgeDia',
    'gripArcDistance',
    'gripCount',
)


def read_grip_inputs(inputs, insert_name):
    """Read the Grip Ridge group back as a GRIP_RIDGE_INSERTS spec tuple.

    Any input that is not there falls back to the stored spec, so this works
    before the group is built and for inserts the dialog never showed.
    """
    spec = list(tm_state.GRIP_RIDGE_INSERTS[insert_name])
    for index, input_id in enumerate(GRIP_RIDGE_INPUTS):
        command_input = inputs.itemById(input_id)
        if command_input:
            spec[index] = command_input.value
    spec[5] = int(spec[5])
    return tuple(spec)


def save_grip_ridge_insert(insert_name, spec, config_file=None):
    """Persist one [GripRidgeInserts] row from a spec tuple."""
    row = ', '.join(str(value) for value in spec)
    return save_values({'GripRidgeInserts': {insert_name: row}}, config_file)


def saved_settings(config_file=None):
    """The settings as config.ini has them, ignoring anything edited since.

    Restore User Saved has to mean the file, not the in-memory CONFIG, which the
    dialog and a previous run will both have written over.
    """
    config = _read_config_file(config_file or _get_config_path())
    defaults = tm_state.DEFAULT_CONFIG
    values = {}
    for _input_id, (key, section) in SETTINGS_INPUTS.items():
        getter = 'boolean' if isinstance(defaults[key], bool) else 'float'
        values[key] = _get(config, key, section, defaults[key], getter)
    return values


def saved_grip_spec(insert_name, config_file=None):
    """One [GripRidgeInserts] row as config.ini has it, or None if it has none."""
    config = _read_config_file(config_file or _get_config_path())
    if not config.has_section('GripRidgeInserts'):
        return None
    for name in config.options('GripRidgeInserts'):
        if name != insert_name:
            continue
        parts = [x.strip() for x in config.get('GripRidgeInserts', name).split(',')]
        if len(parts) != 6:
            return None
        try:
            return (float(parts[0]), float(parts[1]), float(parts[2]),
                    float(parts[3]), float(parts[4]), int(parts[5]))
        except ValueError:
            return None
    return None


def default_grip_spec(insert_name):
    """The shipped spec for a grip insert.

    Falls back to whatever is stored for inserts we do not ship, so restoring a
    user-added insert puts back its config.ini row rather than doing nothing.
    """
    return get_default_grip_ridge_inserts().get(
        insert_name, tm_state.GRIP_RIDGE_INSERTS.get(insert_name))


def read_settings_inputs(inputs):
    """Read the Settings group back as {CONFIG key: value}.

    An input that is not there yet (the group is built last) falls back to the
    loaded CONFIG value, so callers get a complete dict either way.
    """
    values = {}
    for input_id, (key, _section) in SETTINGS_INPUTS.items():
        command_input = inputs.itemById(input_id)
        values[key] = command_input.value if command_input else tm_state.CONFIG.get(key)
    return values


def save_settings(values, config_file=None):
    """Persist {CONFIG key: value} from the Settings group to its config sections."""
    updates = {}
    for _input_id, (key, section) in SETTINGS_INPUTS.items():
        if key in values:
            updates.setdefault(section, {})[key] = values[key]
    return save_values(updates, config_file)


def get_default_inserts():
    """Return the default CNC Kitchen insert specifications."""
    return {
        'M2 x 3mm': (3.2, 3.0, 1.5),
        'M2.5 x 4mm': (4.0, 4.0, 1.5),
        'M3 x 3mm (short)': (4.4, 3.0, 1.6),
        'M3 x 4mm (short)': (4.4, 4.0, 1.6),
        'M3 x 5.7mm (standard)': (4.4, 5.7, 1.6),
        'M4 x 4mm (short)': (5.6, 4.0, 2.0),
        'M4 x 8.1mm (standard)': (5.6, 8.1, 2.0),
        'M5 x 5.8mm (short)': (6.4, 5.8, 2.5),
        'M5 x 9.5mm (standard)': (6.4, 9.5, 2.5),
        'M6 x 12.7mm': (8.0, 12.7, 3.0),
        'M8 x 12.7mm': (9.7, 12.7, 4.0),
        'M10 x 12.7mm': (12.0, 12.7, 5.0),
        '1/4"-20 x 12.7mm (camera)': (8.0, 12.7, 3.0)
    }


def get_default_grip_ridge_inserts():
    """Return the default grip-ridge insert specifications.

    Tuple: (clearance_dia, hole_depth, grip_edge_chamfer,
            grip_ridge_dia, grip_arc_distance, grip_count)
    """
    return {
        'M1.6 Grip':  (1.8,  4,  0.2,  0.8,  1.075, 3),
        'M2 Grip':    (2.2,  5,  0.23, 1.0,  1.35,  3),
        'M2.5 Grip':  (2.7,  6,  0.23, 1.25, 1.725, 3),
        'M3 Grip':    (3.2,  7,  0.28, 1.5,  2.05,  3),
        'M4 Grip':    (4.2,  8,  0.33, 2.0,  2.75,  3),
        'M5 Grip':    (5.3,  9,  0.37, 2.5,  3.5,   4),
        'M6 Grip':    (6.3,  10, 0.42, 2.7,  4.0,   5),
        'M8 Grip':    (8.3,  12, 0.5,  3.5,  5.3,   5),
        'M10 Grip':   (10.3, 14, 0.6,  4.0,  6.45,  6),
    }


def create_default_config(config_file=None):
    """Write a default config.ini file in the new multi-section format."""
    try:
        # Start from the defaults only - anything already loaded would leak into
        # the file we are about to call "default".
        tm_state.INSERT_SPECS.clear()
        tm_state.INSERT_SPECS.update(get_default_inserts())
        tm_state.GRIP_RIDGE_INSERTS.clear()
        tm_state.GRIP_RIDGE_INSERTS.update(get_default_grip_ridge_inserts())
        _write_config_file(config_file)
    except Exception as e:
        if tm_state._ui:
            tm_state._ui.messageBox(f'Could not create config.ini: {str(e)}')
