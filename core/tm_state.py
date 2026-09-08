"""
tm_state.py – Shared state, constants, and globals for ThreadMeister Extended.

All other tm_* modules import from here. This module has no dependencies
on other tm_* modules.
"""
import adsk.core

# Grip-ridge insert specifications: name -> (clearance_dia_mm, hole_depth_mm,
# grip_edge_chamfer_mm, grip_ridge_dia_mm, grip_arc_distance_mm, grip_count)
# Arc grip ridges: N arcs at equal angles, each arc circle has diameter
# grip_ridge_dia_mm, centred grip_arc_distance_mm from the hole centre.
# Filled at startup by tm_config.load_config(), which owns the defaults.
GRIP_RIDGE_INSERTS = {}

# Insert specifications: name -> (hole_diameter_mm, insert_length_mm, min_wall_mm)
# Filled at startup by tm_config.load_config(), which owns the defaults.
INSERT_SPECS = {}

# The shipped defaults. Single source: load_config() falls back to these, and
# the dialog's Restore Defaults resets to them. Never mutated.
DEFAULT_CONFIG = {
    'chamfer_size': 0.5,
    'blind_hole_extra_depth': 1.0,
    'chamfer_enabled_default': True,
    'bottom_radius_size': 0.5,
    'bottom_radius_enabled_default': False,
    'show_success_message': True,
    'enable_logging': False,
    'enable_debug_export': False,
    'hole_type_blind': True,
    'last_selected_insert': 'M3 x 5.7mm (standard)',
    'grip_chamfer_angle': 78,
}

# Runtime configuration (overwritten by tm_config.load_config())
CONFIG = dict(DEFAULT_CONFIG)

# Event handler references (kept in scope to prevent garbage collection)
_handlers = []

# Fusion 360 application and UI handles
try:
    _app = adsk.core.Application.get()
    _ui = _app.userInterface
except Exception:
    _app = None
    _ui = None

# Command identity
# Distinct from the original add-in's 'ThreadMeisterCmd' so both can be installed
CMD_ID = 'ThreadMeisterExtendedCmd'
CMD_NAME = 'ThreadMeister Extended'
CMD_Description = ('Create heat-set insert holes and grip ridge holes '
                   'with CNC Kitchen specifications')

# Toolbar panel
PANEL_ID = 'SolidModifyPanel'  # MODIFY panel in SOLID workspace
