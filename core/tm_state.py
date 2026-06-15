"""
tm_state.py – Shared state, constants, and globals for ThreadMeister.

All other tm_* modules import from here. This module has no dependencies
on other tm_* modules.
"""
import adsk.core

# Tolerance for geometric comparisons
TOL = 1e-6

# ISO metric thread data: major diameter and clearance hole (close fit, mm)
# M1.6 through M10 per ISO 68-1 / ISO 724
M_SERIES_DATA = {
    'M1.6':  (1.6, 1.7),
    'M2':    (2.0, 2.2),
    'M2.5':  (2.5, 2.7),
    'M3':    (3.0, 3.2),
    'M4':    (4.0, 4.3),
    'M5':    (5.0, 5.3),
    'M6':    (6.0, 6.4),
    'M8':    (8.0, 8.4),
    'M10':   (10.0, 10.5),
}

# Grip-ridge insert specifications: name -> (clearance_dia_mm, insert_depth_mm, min_wall_mm, nominal_dia_mm, grip_edge_chamfer_mm)
# Populated at startup by tm_config.load_config(); defaults are set here as fallback.
# Arc grip ridges: 3 arcs at 120°, each arc circle dia = 0.5 * nominal_dia,
# centred at distance 0.6 * nominal_dia from the hole centre.
GRIP_RIDGE_INSERTS = {
    'M1.6 Grip':  (1.7, 4.0, 1.0, 1.6, 0.3),
    'M2 Grip':    (2.2, 5.0, 1.2, 2.0, 0.3),
    'M2.5 Grip':  (2.7, 6.0, 1.5, 2.5, 0.4),
    'M3 Grip':    (3.2, 7.0, 1.6, 3.0, 0.5),
    'M4 Grip':    (4.3, 8.0, 2.0, 4.0, 0.5),
    'M5 Grip':    (5.3, 9.0, 2.5, 5.0, 0.6),
    'M6 Grip':    (6.4, 12.0, 3.0, 6.0, 0.6),
    'M8 Grip':    (8.4, 14.0, 4.0, 8.0, 0.8),
    'M10 Grip':   (10.5, 16.0, 5.0, 10.0, 1.0),
}

# Insert specifications: name -> (hole_diameter_mm, insert_length_mm, min_wall_mm)
# Populated at startup by tm_config.load_config(); defaults are set here as fallback.
INSERT_SPECS = {
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

# Runtime configuration (overwritten by tm_config.load_config())
CONFIG = {
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
    'grip_chamfer_angle': 60,
}

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
CMD_ID = 'ThreadMeisterCmd'
CMD_NAME = 'ThreadMeister'
CMD_Description = 'Create heat-set insert holes with CNC Kitchen specifications'

# Toolbar panel
PANEL_ID = 'SolidModifyPanel'  # MODIFY panel in SOLID workspace
