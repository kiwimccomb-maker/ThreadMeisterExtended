# Changelog

## Unreleased

Added
- **In-dialog Settings group**: chamfer size, blind hole extra depth, bottom
  fillet radius, grip chamfer angle, success message and logging are editable
  from the ThreadMeister dialog. Values apply to the holes being created and are
  saved back to `config.ini` on OK; cancelling changes nothing
- The info panel now recalculates live from those values instead of the last
  loaded config
- `save_values()` edits config.ini line by line rather than round-tripping
  through configparser, which rebuilt the file and **dropped every comment in
  it** - including the format hint above `[GripRidgeInserts]`. This also fixes
  comment loss on the existing checkbox/last-insert saves
- The bottom fillet checkbox no longer bakes the size into its label, which
  would go stale as soon as the size was changed

Correctness
- **Grip-ridge depth on multi-point cuts**: the loop wrote the cm-converted depth
  back over the mm spec value, so the 2nd and later points of one run were cut
  10x too shallow
- **Grip-ridge depth spinner**: the configured hole depth was passed as the
  spinner's step size instead of its initial value, so the dialog opened showing
  the wrong depth and cut it if the dropdown was never touched
- **Grip-ridge chamfers went to the wrong hole**: candidate edges were matched on
  arc radius and plane only, which every other grip hole in the body also
  satisfies. They are now also matched on distance from that hole's centre
- **Bottom-fillet preference was silently cleared**: the saved value was the one
  already ANDed with "blind hole", so cutting a through hole turned the setting off
- **Chamfer edge matching**: perpendicular distance was computed as
  `length - |projection|`, which under-reports badly for edges far along the
  axis; now `sqrt(length^2 - projection^2)`
- **Profile accumulation could hang Fusion**: `combinations()` ran over the full
  candidate list (only the subset size was capped), which is factorial. The
  candidate list itself is now capped at 15
- Re-running the add-in after a failed stop no longer throws on a duplicate
  command definition
- Timeline grouping no longer skipped for the first feature in an empty design
- Info text falls back to a message instead of raising when the remembered
  insert is missing from config.ini
- Grip-ridge chamfer failures log instead of raising a dialog per point

Consistency
- Version is 1.3.2 in `manifest.json`, `ThreadMeister.manifest` and the module
  docstring (all still said 1.2.2)
- `ThreadMeister.manifest` pointed at a `ThreadMeister.svg` that is not in the repo
- Insert names in `config.ini` now match the README, help file and code defaults
  (they were lowercase, so the remembered selection never matched)
- Fallback grip-ridge defaults and `grip_chamfer_angle` matched neither
  `config.ini` nor the README; there is now one set of defaults, in `tm_config`

Cleanup
- Removed dead code: `M_SERIES_DATA`, `clear_log()`, `isSamePoint()`,
  `isSameCircle()`, `calc_blind_hole_depth()`, `_filter_by_bounding_box()`
- `_filter_by_area` passes the centroid through instead of `_filter_by_centroid`
  calling the expensive `areaProperties()` a second time on every profile
- Through-hole search is bounded by the body's bounding box instead of always
  stepping 1000 times
- Per-dialog event handlers no longer accumulate in `tm_state._handlers` on
  every dialog open
- `deploy.bat` / `package.bat` copy `core\*.py` instead of listing each module
- Deleted `requirements.txt` (a pip freeze of an unrelated conda env, with
  unresolvable `file:///` paths); dev dependencies live in `requirements-dev.txt`
- Two test classes shared the name `TestAccumulateProfiles`, so the first one's
  tests never ran; the grip-ridge chamfer tests were calling a signature that no
  longer existed

## 1.3.2 - Grip ridge chamfer parameters
- Grip ridge chamfer parameters reworked: `grip_edge_chamfer` values increased
  and `grip_chamfer_angle` raised to 78 degrees, since chamfers applied through
  the grip ridge parameters do not behave like manually added chamfers
- Fixed the default hole depth used for grip ridge inserts

## 1.3.1 - Bug fixes and improvements

## 1.3.0 - Advanced parameters and customization
- Advanced per-size parameters for grip ridge inserts: clearance diameter, hole
  depth, grip edge chamfer, grip ridge diameter, grip arc distance and grip count
- `config.ini` gained the `[GripRidgeInserts]` section carrying all six values
- Tests covering the new configuration options

## 1.2.2 — 2026-03-16 — Config restructure & depth fix
- **Config.ini reorganized** into 4 sections: `[Settings]`, `[Inserts]`, `[UI State]`, `[Developer]`
- Auto-migration: old single-section configs are upgraded automatically on load
- **Chamfer depth fix**: chamfer size is now added to blind hole extrude depth (was missing before)
- Info text updates dynamically when toggling chamfer checkbox
- **Improved error messages**: failure dialogs now show per-point details
- Shared `calc_blind_hole_depth_mm()` helper eliminates depth formula duplication
- Updated README config parameter documentation with section descriptions
- Bundled `resources/help.html` reference documentation

## 1.2.1 — 2026-03-14 — Privacy policy & packaging
- Added privacy policy section to README (required for Autodesk App Store)
- Added `package.bat` script for creating App Store zip packages

## 1.2.0 — 2026-03-14 — Clean temp sketch approach
- **Major redesign of bore creation**: replaced drawing bore circle in user's sketch with creating a clean temporary sketch via `addWithoutEdges(face)`
- **Problem solved**: Fusion 360 auto-projects 3D body edges onto sketch planes as reference curves, which split bore profiles unpredictably and caused extrusion failures
- **New flow**: create projection-free temp sketch → project original point (parametric link) → draw bore circle → trivial 2-profile selection
- Temp sketches named `TM_{insert}_P{n}`, included in timeline group
- On failure, temp sketch is deleted and point is skipped — user's original sketch is never modified
- Added `isReference` curve skip in `_filter_by_curve_points`
- Added `is_reference` field to debug export curve data
- Removed all `log()` calls from `tm_geometry.py` and `tm_execute.py`
- Removed `diagnose_blind_hole()` diagnostic function
- Deleted scratch scripts (`analyze_loop3.py`, `test_curves_debug.py`, `test_import.py`)
- Updated `development-notes.md` with Phase 5 documentation
- ✅ All tests passing, verified in Fusion 360

## 1.1.2 — 2026-03-13 — Export & visualization infrastructure
- Added `tm_debug_export.py` for JSON export of sketch profiles/curves from Fusion 360
- Added `visualize_profiles.py` standalone matplotlib visualization tool
- Added `profile_inspector.py` interactive profile/curve inspector
- Added `test_profile_selection.py` fixture-based tests
- Added curve-point filter (`_filter_by_curve_points`) to `findProfileForCircle`
- Standardized logging with `[TM][filter_name]` prefix format
- Added debug export UI: `exportDebug` checkbox in dialog (behind `enable_debug_export` config flag)
- Export produces dual output: Fusion console `[EXPORT]` messages + JSON files to `debug_exports/`

## 1.1.1 — 2026-03-11 — Pytest test suite
- Added 49 comprehensive unit tests covering `tm_helpers`, `tm_config`, and `tm_geometry` filter functions
- Mock-based testing with zero Fusion 360 dependency
- `conftest.py` handles `adsk` module stubbing before imports
- Added test infrastructure: `pytest.ini`, `requirements-dev.txt`, `.venv` setup
- All tests pass and ready for CI/CD integration

## 1.1.0b — 2026-03-10 — Code organization & sub-function refactoring
- **Modules moved to `core/` subdirectory** for cleaner project structure
- **Updated deploy script** to copy modules from `core/` subdirectory
- **Refactored `findProfileForCircle()`** into testable sub-functions:
  - `_filter_by_area()` – coarse area validation
  - `_filter_by_centroid()` – coarse centroid distance check
  - `_filter_by_bounding_box()` – coarse bounding box containment
  - `_accumulate_profiles()` – precise profile area matching
- **Improved code testability** – each filter function can be tested independently
- **Foundation for Phase 2** – prepares for pytest unit tests and Phase 3 fixture-based testing
- No functional changes – all features work identically to v1.1.0
- ✅ Verified working in Fusion 360 (blind holes, through holes, chamfer, fillet)

## 1.1.0 — 2026-03-09 — Refactoring into modules
- Split monolithic `ThreadMeister.py` (~1500 lines) into 6 focused modules:
  - `tm_state.py` – shared globals, constants
  - `tm_config.py` – config loading, validation, saving
  - `tm_helpers.py` – geometry comparisons, logging, `calc_blind_hole_depth()`
  - `tm_geometry.py` – profile finding, extrusion, chamfer, fillet
  - `tm_execute.py` – `CommandExecuteHandler` (main hole creation loop)
  - `tm_ui.py` – UI event handlers, info text
- `ThreadMeister.py` is now a thin entry point (`run()` / `stop()` only)
- Removed dead code (duplicate import/config block from lines 1221-1249)
- No functional changes – identical behaviour to v1.0.1

## 1.0.1 — 2026-03-07 — Documentation update
- Switched license from GPL-3.0 to MIT
- Added animated GIF demo to README and App Store README
- Added "Why ThreadMeister?" section to both READMEs
- Added ScreenToGif credit
- README layout improvements (centered headline, image spacing)
- Cleaned up duplicate icon files from resources/ root

## 1.0.0 — 2026-02 — Initial Release
- First public release of ThreadMeister.
- Distributed simultaneously on **GitHub** and the **Autodesk App Store** (release pending).
- Tested on Windows; macOS support expected but not tested
- Known limitation: through‑hole extrusions may fail in certain sketch or geometry configurations
- Added support for all CNC Kitchen insert sizes (M2–M10, 1/4"-20).
- Added blind and through hole options.
- Added automatic chamfer and optional bottom fillet.
- Added multi-point hole creation.
- Added timeline grouping for clean parametric workflows.
- Added SOLID → MODIFY menu integration.
- Added documentation and packaging for the Autodesk App Store.



