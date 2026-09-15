"""Timestamped, append-only log of every Api method call the GUI makes
- method name, arguments (secrets redacted), outcome, duration -
written to one running file per GUI session. Ported as-is from the
sibling AOS8-to-AOS10 Conversion Tool project's own action_log.py.

Deliberately does NOT do the logging itself inside Api - see
gui/api.py's Api._wrap_methods_for_logging, which wraps every public
method on the instance at construction time rather than decorating
each method by hand.

Opt-in, same convention as Transcript: Api(action_log=None) - the
default, used by every test and every direct `Api()` construction -
changes nothing. Only gui/app.py's real entry point passes a real
ActionLog in - wiring logging on by default inside Api itself would
mean every test that constructs Api() bare starts writing real files
into the real project's Command Outputs/session-logs/ directory on
every run.

Redaction is name-pattern-based, not per-method-special-cased: any
parameter whose name (lowercased) is in _SENSITIVE_PARAM_NAMES gets
replaced with "<redacted>", regardless of which Api method it belongs
to."""

from __future__ import annotations

import inspect
import json
import threading
from datetime import datetime
from pathlib import Path

DEFAULT_LOG_DIR = Path("Command Outputs") / "session-logs"

_SENSITIVE_PARAM_NAMES = {
    "password", "client_secret", "csecret", "refresh_token", "secret",
}


def _redact_arguments(sig: inspect.Signature, args: tuple, kwargs: dict) -> dict:
    """Best-effort - a call that doesn't bind cleanly against the
    method's own signature falls back to not recording argument values
    at all, rather than risking an unredacted dump."""
    try:
        bound = sig.bind_partial(*args, **kwargs)
    except TypeError:
        return {"_unbindable": True}
    return {
        name: "<redacted>" if name.lower() in _SENSITIVE_PARAM_NAMES else value
        for name, value in bound.arguments.items()
    }


class ActionLog:
    def __init__(self, log_dir: Path | None = None):
        self.log_dir = log_dir or DEFAULT_LOG_DIR
        self.path: Path | None = None
        self._fh = None
        self._lock = threading.Lock()

    def log(
        self,
        method: str,
        sig: inspect.Signature,
        args: tuple,
        kwargs: dict,
        ok: bool,
        error: str | None,
        duration_s: float,
    ) -> None:
        record = {
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "method": method,
            "args": _redact_arguments(sig, args, kwargs),
            "ok": ok,
            "error": error,
            "duration_s": round(duration_s, 3),
        }
        line = json.dumps(record, default=str)
        with self._lock:
            if self._fh is None:
                self.log_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                self.path = self.log_dir / f"gui-actions_{stamp}.jsonl"
                self._fh = self.path.open("a", encoding="utf-8")
            self._fh.write(line + "\n")
            self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
