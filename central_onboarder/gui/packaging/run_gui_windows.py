"""PyInstaller's Analysis needs a plain script entry point - this is
that script. Kept to one line on purpose, same as the sibling AOS8-to-
AOS10 Conversion Tool's run_gui_windows.py; all real logic stays in
central_onboarder/gui/app.py, imported normally so it's exercised
identically to running `python -m central_onboarder.gui.app` directly
(no packaging-only code path to drift from what's actually tested)."""

from central_onboarder.gui.app import main

if __name__ == "__main__":
    main()
