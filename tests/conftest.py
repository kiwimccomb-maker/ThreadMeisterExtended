"""
Pytest configuration and shared fixtures.

CRITICAL: Must mock adsk module BEFORE any project imports,
since tm_state calls adsk.core.Application.get() at module import time.
"""

import sys
import os
from unittest.mock import MagicMock

# Stub adsk module before any project imports
adsk_mock = MagicMock()
adsk_mock.core.Application.get.return_value = MagicMock()
adsk_mock.fusion.CalculationAccuracy.MediumCalculationAccuracy = MagicMock()
adsk_mock.core.SurfaceTypes = MagicMock()
adsk_mock.core.SurfaceTypes.PlaneSurfaceType = 'PlaneSurfaceType'
adsk_mock.core.Curve3DTypes = MagicMock()
adsk_mock.core.Curve3DTypes.Circle3DCurveType = 'Circle3DCurveType'
adsk_mock.core.Curve3DTypes.Arc3DCurveType = 'Arc3DCurveType'

# Mock ObjectCollection to be iterable and countable
def create_object_collection():
    """Create a mock ObjectCollection that supports iteration and count."""
    class MockObjectCollection:
        def __init__(self):
            self._items = []

        def add(self, item):
            self._items.append(item)

        @property
        def count(self):
            return len(self._items)

        def item(self, index):
            return self._items[index]

        def __iter__(self):
            return iter(self._items)

        def __len__(self):
            return len(self._items)

    return MockObjectCollection()

adsk_mock.core.ObjectCollection.create = create_object_collection

# Handler classes subclass these, so they must be real classes, not MagicMocks
class _FakeEventHandler:
    pass

for _handler_name in ('CommandEventHandler', 'CommandCreatedEventHandler',
                      'InputChangedEventHandler', 'ValidateInputsEventHandler'):
    setattr(adsk_mock.core, _handler_name, _FakeEventHandler)

sys.modules['adsk'] = adsk_mock
sys.modules['adsk.core'] = adsk_mock.core
sys.modules['adsk.fusion'] = adsk_mock.fusion

# Add core/ to path so we can import tm_* modules
_core_path = os.path.join(os.path.dirname(__file__), '..', 'core')
if _core_path not in sys.path:
    sys.path.insert(0, _core_path)

# Now safe to import tm_state and suppress messageBox calls
import tm_state
tm_state._ui = None
# Logging disabled by default - set to True to see algorithm debug output
tm_state.CONFIG['enable_logging'] = False

# Override log function to print to stdout during tests (optional for debugging)
import tm_helpers
_original_log = tm_helpers.log
def debug_log(msg):
    """Log to stdout for debugging tests."""
    if tm_state.CONFIG.get('enable_logging', False):
        print(msg)
tm_helpers.log = debug_log


# --- Shared fixtures -------------------------------------------------------
import io as _io

import pytest

SAMPLE_CONFIG = """[Settings]
chamfer_size = 0.5
blind_hole_extra_depth = 1.0
bottom_radius_size = 0.5
grip_chamfer_angle = 78

[Inserts]
M3 x 5.7mm (standard) = 4.4, 5.7, 1.6
M4 x 8.1mm (standard) = 5.6, 8.1, 2.0

[GripRidgeInserts]
# Format: clearance_dia, hole_depth, grip_edge_chamfer, grip_ridge_dia, grip_arc_distance, grip_count
M3 Grip = 3.2, 7, 0.28, 1.5, 2.05, 3

[UI State]
chamfer_enabled_default = True
bottom_radius_enabled_default = True
show_success_message = False
hole_type_blind = True
last_selected_insert = M3 x 5.7mm (standard)

[Developer]
enable_logging = False
enable_debug_export = False
"""


@pytest.fixture
def config_file(tmp_path):
    """A throwaway config.ini with one insert, one grip insert and a comment."""
    path = tmp_path / 'config.ini'
    _io.open(str(path), 'w', encoding='utf-8', newline='\n').write(SAMPLE_CONFIG)
    return str(path)


class RecordingInputs:
    """Minimal stand-in for Fusion's CommandInputs that records what was added."""

    def __init__(self):
        self.spinners = {}
        self.integers = {}
        self.bools = {}
        self.groups = {}
        self.tooltips = {}
        self.order = []
        self.collapsed = {}
        self.rows = {}
        self.row_items = {}

    def _record_tooltip(self, input_id):
        self.order.append(input_id)
        holder = self

        class _Input:
            id = input_id
            value = None

            def __setattr__(self, name, val):
                if name == 'tooltip':
                    holder.tooltips[input_id] = val
                else:
                    object.__setattr__(self, name, val)

        return _Input()

    def itemById(self, input_id):
        return None

    def addButtonRowCommandInput(self, input_id, name, _multi):
        holder = self
        holder.rows[input_id] = name

        class _Items:
            @staticmethod
            def add(label, isSelected, folder=''):
                holder.row_items.setdefault(input_id, []).append((label, folder))

            count = 0

        row = holder._record_tooltip(input_id)
        object.__setattr__(row, 'listItems', _Items())
        return row

    def addGroupCommandInput(self, input_id, name):
        holder = self
        self.groups[input_id] = name
        self.collapsed[input_id] = False

        class _Group:
            children = holder
            isVisible = True

            def __setattr__(self, attr, val):
                if attr == 'isExpanded':
                    holder.collapsed[input_id] = not val
                else:
                    object.__setattr__(self, attr, val)

        return _Group()

    def addFloatSpinnerCommandInput(self, input_id, name, unit, minimum,
                                    maximum, step, initial):
        self.spinners[input_id] = {'name': name, 'unit': unit, 'min': minimum,
                                   'max': maximum, 'step': step, 'initial': initial}
        return self._record_tooltip(input_id)

    def addIntegerSpinnerCommandInput(self, input_id, name, minimum, maximum,
                                      step, initial):
        self.integers[input_id] = {'name': name, 'min': minimum, 'max': maximum,
                                   'step': step, 'initial': initial}
        return self._record_tooltip(input_id)

    def addBoolValueInput(self, input_id, name, _has_icon, _folder, initial):
        self.bools[input_id] = {'name': name, 'initial': initial}
        return self._record_tooltip(input_id)


@pytest.fixture
def recording_inputs():
    return RecordingInputs()
