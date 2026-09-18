# Windows packaging (PyInstaller, onedir)

Status: **built AND live-verified** (2026-09-17) - first real native
Windows build of this app, produced and run on this machine.

## Why onedir, not onefile or an installer

Same call as the sibling AOS8-to-AOS10 Conversion Tool project (spec
review 2026-08-18, not re-litigated here): no code-signing budget for
field/partner laptop distribution, so a plain unzip-and-run folder + an
expected AV-exception heads-up is the accepted tradeoff over building
real installer/signing infrastructure.

## Releasing a new build

Before running the build command below, bump the version and log what
changed - the whole point of `central_onboarder/version.py` existing as
a single source of truth (see that module's own docstring):

1. Bump `VERSION` in `central_onboarder/version.py`, and `version` in
   `pyproject.toml` to match (kept in sync by hand - `version.py` may
   run frozen, outside pyproject.toml's source tree).
2. Add a dated entry to `central_onboarder/assets/CHANGELOG.md`, newest
   first - terse, user-facing bullet points under **New features**/
   **Fixes**, not a full engineering log of every change made.
3. Then build as below. The sidebar's version number reads this at
   runtime (`gui/app.py`'s window title, `Api.get_version`) - nothing
   else to wire up.

## How to build

From the repo root:

```
python -m venv .venv
.venv\Scripts\pip install ".[gui,windows-build]"
.venv\Scripts\pyinstaller central_onboarder/gui/packaging/central-onboarder-gui-windows.spec
```

Produces `dist/Central Onboarder/Central Onboarder.exe` plus its
`_internal/` support folder. Double-click the `.exe` directly - no
install step. Distribute by zipping the whole `Central Onboarder/`
folder; the operator unzips it anywhere and runs the `.exe` inside.

## What's actually confirmed live (2026-09-17), not guessed

1. **The build itself completes cleanly.** `pip install ".[gui,
   windows-build]"` + the `pyinstaller ... .spec` command above ran
   with zero errors (PyInstaller 6.22.3, Python 3.14). Only warning was
   for `pycparser.lextab`/`yacctab` (cffi's optional generated tables,
   unrelated, harmless) - same benign warning the sibling project's own
   build hits.
2. **The window actually opens and renders the real UI** - not a blank
   page, not a crash. Screenshotted directly (Win32 `GetWindowRect` +
   `CopyFromScreen` via PowerShell, since there's no browser-automation
   path into a native pywebview window): Home screen, sidebar nav
   (Credentials/Device List/Onboard/Assign Site/Tools), and body text
   all rendered correctly. Window title reads `Central Onboarder
   v0.3.1`, confirming `version.py` and the frozen build agree.
3. **`central_onboarder/gui/static/` and `central_onboarder/assets/
   *.xlsx`/`*.md` land exactly where `app.py`'s `_static_dir()` and
   `resources.files("central_onboarder.assets")` expect** (`_internal/
   central_onboarder/gui/static/...`, `_internal/central_onboarder/
   assets/...`) - confirmed by inspecting the built `dist/` tree
   directly, not assumed from the spec's `datas` list alone.
4. **`credentials.json`/`workspace.json` resolve next to the real
   `.exe`, not inside `_internal/`** - `core/credential_store.py`'s and
   `core/workspace.py`'s `default_path()` were already ported
   frozen-aware from the sibling project before this packaging work
   started (branches on `sys.frozen`, uses `Path(sys.executable).
   resolve().parent`), and each has direct unit-test coverage
   (`test_default_path_is_next_to_the_exe_when_frozen` in `tests/
   test_credential_store.py` and `tests/test_workspace.py`) - not
   re-verified live against the frozen build this session, but this
   exact code path was proven live in the sibling project.

## Not yet click-verified

- **`resources.files("central_onboarder.assets")` actually being
  *read* at runtime** (e.g. the Home screen's User Guide link, or a
  sheet-build action that loads `device_list_template.xlsx`) -
  confirmed the files are physically present in the bundle at the
  right path (see #3 above), but reading them back through the real
  frozen import path needs a real UI click this session didn't
  automate (no native-window click tool was used - screenshotting was
  done via raw Win32 calls, clicking wasn't attempted). PyInstaller's
  default onedir layout (loose data files alongside a PYZ-archived
  package) is the standard supported case for `importlib.resources`,
  so this is expected to work, but "expected to work" isn't
  "confirmed" - flag if this ever surfaces as a real problem.
- **Any real device/API-touching action** (New Central, Classic
  Central, GLCP) - this session only verified the app launches and
  renders correctly, not that `requests`' bundling actually works for
  a real API call once frozen. Worth a real credentials-test-all pass
  next time this is picked up.
- **Distribution-as-zip-and-unzip specifically** - built and run
  in-place under `dist/`, not zipped, moved to a different machine, and
  unzipped there. The onedir folder is self-contained by design, so
  this should be a non-issue, but "should be" isn't "confirmed."
