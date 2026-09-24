import pytest

from central_onboarder.core import credential_store


@pytest.fixture(autouse=True)
def _isolate_credential_files(tmp_path_factory, monkeypatch):
    """No test may ever read or write the real token.yaml or legacy
    credentials.json next to the app - redirect the app directory both
    are resolved from to a throwaway folder. Tests that patch
    default_path themselves still work (they patch on top of this)."""
    app_dir = tmp_path_factory.mktemp("appdir")
    monkeypatch.setattr(credential_store, "_app_dir", lambda: app_dir)
