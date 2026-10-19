import json
import subprocess
import sys

import pytest

from loader.expense_loader import FIELDS
from scripts.export_json import export_json
from scripts.sample_data import generate_sample


def test_exports_validated_records_and_errors(tmp_path):
    source = generate_sample(tmp_path / "sample.csv")
    output = export_json(source, tmp_path / "nested" / "sample.json")
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert len(payload["expenses"]) == 22
    assert len(payload["errors"]) == 8
    assert payload["expenses"][0] == {
        "id": "EXP-001", "employee": "Alice Morgan", "date": "2026-10-05",
        "category": "meals", "amount": "20.00", "description": "Team lunch",
        "receipt_attached": True,
        "submission_date": "2026-10-05",
        "nights": None,
    }
    assert payload["expenses"][4]["receipt_attached"] is False
    assert payload["errors"][0] == {
        "line_number": 12, "expense_id": "BAD-001",
        "reasons": ["employee: required field is empty"],
    }
    assert payload["errors"][6]["expense_id"] is None
    hotel = next(item for item in payload["expenses"] if item["id"] == "EXP-015")
    assert hotel["nights"] == 2


def test_exports_available_id_for_field_count_error(tmp_path):
    source = tmp_path / "expenses.csv"
    source.write_text(",".join(FIELDS) + "\n EXP-123 ,Alice,2024-02-29,meals,25.00,Lunch,false,2024-03-01\n")
    output = export_json(source, tmp_path / "out.json")
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {
        "expenses": [],
        "errors": [{
            "line_number": 2, "expense_id": "EXP-123",
            "reasons": ["Expected 9 fields, got 8"],
        }],
    }


def test_protects_existing_output_and_source(tmp_path):
    source = generate_sample(tmp_path / "sample.csv")
    original = source.read_bytes()
    with pytest.raises(ValueError, match="different files"):
        export_json(source, source, overwrite=True)
    alias = tmp_path / "alias.csv"
    alias.symlink_to(source)
    with pytest.raises(ValueError, match="different files"):
        export_json(source, alias, overwrite=True)
    assert source.read_bytes() == original
    output = tmp_path / "out.json"
    output.write_text("existing")
    with pytest.raises(FileExistsError):
        export_json(source, output)
    assert output.read_text() == "existing"
    export_json(source, output, overwrite=True)
    assert len(json.loads(output.read_text())["expenses"]) == 22


def test_invalid_input_leaves_output_untouched(tmp_path):
    source = tmp_path / "bad.csv"
    source.write_text("bad headers\n")
    output = tmp_path / "out.json"
    output.write_text("existing")
    with pytest.raises(ValueError):
        export_json(source, output, overwrite=True)
    assert output.read_text() == "existing"


def test_export_cli(tmp_path):
    source = generate_sample(tmp_path / "sample.csv")
    output = tmp_path / "out.json"
    command = [sys.executable, "-m", "scripts.export_json", "--input", str(source), "--output", str(output)]
    success = subprocess.run(command, capture_output=True, text=True)
    assert success.returncode == 0
    assert len(json.loads(output.read_text())["expenses"]) == 22
    failure = subprocess.run(command, capture_output=True, text=True)
    assert failure.returncode == 1
    assert "Error:" in failure.stderr
    assert "Traceback" not in failure.stderr
