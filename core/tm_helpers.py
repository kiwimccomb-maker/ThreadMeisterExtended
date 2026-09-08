"""
tm_helpers.py – Utility functions: blind hole depth, logging.
"""
import adsk.core
import tm_state


def calc_blind_hole_depth_mm(insert_len_mm, extra_depth_mm, chamfer_mm=0.0):
    """
    Calculate the total blind hole depth in mm.

    Args:
        insert_len_mm: Insert length in mm
        extra_depth_mm: Extra clearance depth in mm
        chamfer_mm: Chamfer size in mm (added when chamfer is enabled)

    Returns:
        Total depth in mm as a float.
    """
    return insert_len_mm + extra_depth_mm + chamfer_mm


def log(msg):
    """Write a message to Fusion's Text Commands palette (only if logging enabled)."""
    try:
        if not tm_state.CONFIG.get('enable_logging', False):
            return
        app = adsk.core.Application.get()
        ui = app.userInterface
        p = ui.palettes.itemById('TextCommands')
        if not p.isVisible:
            p.isVisible = True
        p.writeText(str(msg))
    except Exception:
        try:
            print(str(msg))
        except Exception:
            pass
