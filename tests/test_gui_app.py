from central_onboarder.gui import app as app_module
from central_onboarder.gui.api import Api
from central_onboarder.version import VERSION


def test_static_dir_resolves_next_to_app_py_in_dev_mode():
    static_dir = app_module._static_dir()
    assert static_dir.name == "static"
    assert (static_dir / "index.html").exists()
    assert (static_dir / "js" / "app.js").exists()
    assert (static_dir / "css" / "app.css").exists()


def test_module_level_version_matches_version_module():
    assert app_module.VERSION == VERSION


def test_api_importable_without_pywebview_window():
    """Api() must be constructible without an actual pywebview window
    existing - every test in this suite relies on that."""
    api = Api()
    assert api.get_version() == {"version": VERSION}
