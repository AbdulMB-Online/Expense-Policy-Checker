import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.loader.policy_loader import load_policy
from backend.scripts.export_policy import export_policy

POLICY_PATH = Path(__file__).resolve().parents[1] / "data" / "policy" / "policy.json"


def test_exports_validated_policy(tmp_path):
    output = export_policy(POLICY_PATH, tmp_path / "nested" / "policy.json")
    expected = load_policy(POLICY_PATH)
    text = output.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert text == json.dumps(expected, indent=2, ensure_ascii=False) + "\n"
    assert payload == expected
    assert payload["categories"]["meals"]["max_amount"] == "50.00"


def test_protects_existing_output_and_source(tmp_path):
    source = tmp_path / "policy.json"
    source.write_text(POLICY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    original = source.read_bytes()
    with pytest.raises(ValueError, match="different files"):
        export_policy(source, source, overwrite=True)
    output = tmp_path / "out.json"
    output.write_text("existing")
    with pytest.raises(FileExistsError):
        export_policy(source, output)
    assert output.read_text() == "existing"
    export_policy(source, output, overwrite=True)
    assert json.loads(output.read_text())["currency"] == "USD"
    assert source.read_bytes() == original


def test_invalid_input_leaves_output_untouched(tmp_path):
    source = tmp_path / "policy.json"
    source.write_text('{"version": "1"}', encoding="utf-8")
    output = tmp_path / "out.json"
    output.write_text("existing")
    with pytest.raises(ValueError):
        export_policy(source, output, overwrite=True)
    assert output.read_text() == "existing"


def test_export_cli(tmp_path):
    source = tmp_path / "policy.json"
    source.write_text(POLICY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    output = tmp_path / "out.json"
    command = [sys.executable, "-m", "backend.scripts.export_policy", "--input", str(source), "--output", str(output)]
    success = subprocess.run(command, capture_output=True, text=True)
    assert success.returncode == 0
    assert json.loads(output.read_text())["name"]
    failure = subprocess.run(command, capture_output=True, text=True)
    assert failure.returncode == 1
    assert "Error:" in failure.stderr
    assert "Traceback" not in failure.stderr
