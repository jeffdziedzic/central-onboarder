import inspect
import json
from pathlib import Path

from central_onboarder.core.action_log import ActionLog


def _sig():
    def f(password=None, account=None):
        pass

    return inspect.signature(f)


def test_log_writes_one_json_line(tmp_path: Path):
    log = ActionLog(log_dir=tmp_path)
    log.log("save_central", _sig(), (), {"account": "acme"}, ok=True, error=None, duration_s=0.01)
    log.close()
    files = list(tmp_path.glob("gui-actions_*.jsonl"))
    assert len(files) == 1
    record = json.loads(files[0].read_text().strip())
    assert record["method"] == "save_central"
    assert record["ok"] is True
    assert record["args"] == {"account": "acme"}


def test_log_redacts_sensitive_params(tmp_path: Path):
    log = ActionLog(log_dir=tmp_path)
    log.log("save_central", _sig(), (), {"account": "acme", "password": "hunter2"}, ok=True, error=None, duration_s=0.0)
    log.close()
    record = json.loads(next(tmp_path.glob("gui-actions_*.jsonl")).read_text().strip())
    assert record["args"]["password"] == "<redacted>"
    assert record["args"]["account"] == "acme"


def test_log_records_error(tmp_path: Path):
    log = ActionLog(log_dir=tmp_path)
    log.log("save_central", _sig(), (), {}, ok=False, error="boom", duration_s=0.0)
    log.close()
    record = json.loads(next(tmp_path.glob("gui-actions_*.jsonl")).read_text().strip())
    assert record["ok"] is False
    assert record["error"] == "boom"
