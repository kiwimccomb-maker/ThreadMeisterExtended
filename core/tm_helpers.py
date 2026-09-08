"""
tm_helpers.py – Utility functions: blind hole depth, logging.
"""
import math

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


def grip_ridge_warning(clearance_dia, ridge_dia, arc_distance, ridge_count):
    """Say why a grip ridge combination will not cut, or None if it is sound.

    Each ridge circle has to cross the bore wall to leave a lobe protruding into
    the bore, and the ridges must not run into each other. All in mm.
    """
    bore_r = clearance_dia / 2.0
    ridge_r = ridge_dia / 2.0

    if arc_distance >= bore_r + ridge_r:
        return ('Ridges sit outside the bore: reduce the ridge distance '
                'or increase the ridge diameter.')
    if arc_distance <= abs(bore_r - ridge_r):
        return ('Ridges swallow the bore wall: increase the ridge distance '
                'or reduce the ridge diameter.')
    if ridge_count > 1:
        gap = 2.0 * arc_distance * math.sin(math.pi / ridge_count)
        if gap <= ridge_dia:
            return (f'{ridge_count} ridges overlap each other: reduce the count '
                    'or the ridge diameter.')
    return None


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
