"""Timestamped, append-only transcripts of every API command this
project runs against a real tenant - host, command, raw response -
written to a file so a live sample survives even if a terminal scrolls
past or the session closes. Ported as-is from the sibling
AOS8-to-AOS10 Conversion Tool project's own transcript.py.

Lazily creates its file on the first record() call, not at
construction - an action that never actually reaches a device (e.g. a
missing-credentials error) shouldn't leave an empty log file behind.

`on_record` is an optional callback invoked with (host, command, text)
every time record() is, in addition to the file write, never instead
of it. Any exception it raises is swallowed - a bug in a GUI's display
code must never be able to interrupt a live API operation."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

DEFAULT_LOG_DIR = Path("Command Outputs") / "session-logs"


class Transcript:
    def __init__(
        self, log_dir: Path | None = None, prefix: str = "session",
        on_record: Callable[[str, str, str], None] | None = None,
    ):
        self.log_dir = log_dir or DEFAULT_LOG_DIR
        self._prefix = prefix
        self._on_record = on_record
        self.path: Path | None = None
        self._fh = None
        self._lock = threading.Lock()

    def record(self, host: str, command: str, output: object) -> None:
        text = output if isinstance(output, str) else json.dumps(output, indent=2)
        timestamp = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            if self._fh is None:
                self.log_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                self.path = self.log_dir / f"{self._prefix}_{stamp}.log"
                self._fh = self.path.open("a", encoding="utf-8")
            self._fh.write(f"=== {timestamp} {host} - {command} ===\n{text}\n\n")
            self._fh.flush()
            if self._on_record is not None:
                try:
                    self._on_record(host, command, text)
                except Exception:
                    pass

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
