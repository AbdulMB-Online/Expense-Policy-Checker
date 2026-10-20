import json
from pathlib import Path

import pytest

from backend.loader.policy_loader import load_policy


POLICY_PATH = Path(__file__).resolve().parents[1] / "data" / "policy" / "policy.json"


@pytest.fixture
def policy():
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def write_policy(tmp_path, policy):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    return path


def test_loads_real_policy_without_changing_values():
    expected = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    loaded = load_policy(POLICY_PATH)
    assert loaded == expected
    assert loaded["categories"]["meals"]["max_amount"] == "50.00"
    assert loaded["categories"]["hotel"]["max_nights_per_stay"] is None
    assert loaded["submission"]["inclusive"] is True


def test_custom_policy_categories_and_values_are_data(tmp_path, policy):
    policy["categories"] = {
        "conference": {
            "max_amount": "1234.56",
            "limit_basis": "per_expense",
            "receipt": {"mode": "above_threshold", "threshold": "0.00"},
            "review_required": False,
        }
    }
    policy["restricted_categories"] = ["personal"]
    policy["submission"]["max_days_after_expense"] = 0
    policy["duplicates"]["flag"] = "later_matches"
    assert load_policy(write_policy(tmp_path, policy)) == policy


@pytest.mark.parametrize("path,value", [
    (("version",), ""),
    (("name",), "   "),
    (("currency",), "usd"),
    (("currency",), "US"),
    (("currency",), 123),
    (("categories",), []),
    (("categories", "meals", "max_amount"), 50),
    (("categories", "meals", "max_amount"), True),
    (("categories", "meals", "max_amount"), "-1.00"),
    (("categories", "meals", "max_amount"), "NaN"),
    (("categories", "meals", "max_amount"), "Infinity"),
    (("categories", "meals", "max_amount"), "1.001"),
    (("categories", "meals", "max_amount"), "1e2"),
    (("categories", "meals", "limit_basis"), "per_week"),
    (("categories", "meals", "receipt", "mode"), "sometimes"),
    (("categories", "meals", "receipt", "threshold"), None),
    (("categories", "meals", "receipt", "threshold"), 25),
    (("categories", "meals", "receipt", "threshold"), "-0.01"),
    (("categories", "meals", "receipt", "threshold"), "NaN"),
    (("categories", "meals", "receipt", "threshold"), "1.001"),
    (("categories", "hotel", "nights_required"), 1),
    (("categories", "hotel", "max_nights_per_stay"), True),
    (("categories", "hotel", "max_nights_per_stay"), 0),
    (("categories", "hotel", "max_nights_per_stay"), -1),
    (("categories", "hotel", "max_nights_per_stay"), 1.5),
    (("categories", "other", "review_required"), "true"),
    (("restricted_categories",), "alcohol"),
    (("restricted_categories",), ["alcohol", "alcohol"]),
    (("restricted_categories",), [""]),
    (("restricted_categories",), [5]),
    (("unknown_category_action",), "approve"),
    (("submission", "max_days_after_expense"), True),
    (("submission", "max_days_after_expense"), -1),
    (("submission", "max_days_after_expense"), 1.5),
    (("submission", "inclusive"), 1),
    (("duplicates", "key_fields"), []),
    (("duplicates", "key_fields"), ["date", "date"]),
    (("duplicates", "key_fields"), ["unknown"]),
    (("duplicates", "key_fields"), "date"),
    (("duplicates", "require_different_ids"), "true"),
    (("duplicates", "flag"), "first_match"),
    (("duplicates", "classification"), "confirmed_duplicate"),
    (("reporting", "collect_all_violations"), 1),
    (("reporting", "flagged_amount_counting"), "per_violation"),
])
def test_rejects_invalid_schema_values(tmp_path, policy, path, value):
    parent = policy
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises(ValueError):
        load_policy(write_policy(tmp_path, policy))


@pytest.mark.parametrize("key", [
    "version", "name", "currency", "categories", "restricted_categories",
    "unknown_category_action", "submission", "duplicates", "reporting",
])
def test_requires_root_fields(tmp_path, policy, key):
    del policy[key]
    with pytest.raises(ValueError):
        load_policy(write_policy(tmp_path, policy))


@pytest.mark.parametrize("path", [
    (), ("categories", "meals"), ("categories", "meals", "receipt"),
    ("submission",), ("duplicates",), ("reporting",),
])
def test_rejects_unknown_schema_fields(tmp_path, policy, path):
    parent = policy
    for key in path:
        parent = parent[key]
    parent["unexpected"] = True
    with pytest.raises(ValueError):
        load_policy(write_policy(tmp_path, policy))


@pytest.mark.parametrize("path,key", [
    (("categories", "meals"), "max_amount"),
    (("categories", "meals"), "limit_basis"),
    (("categories", "meals"), "receipt"),
    (("categories", "meals", "receipt"), "mode"),
    (("categories", "meals", "receipt"), "threshold"),
    (("submission",), "max_days_after_expense"),
    (("submission",), "inclusive"),
    (("duplicates",), "key_fields"),
    (("duplicates",), "require_different_ids"),
    (("duplicates",), "flag"),
    (("duplicates",), "classification"),
    (("reporting",), "collect_all_violations"),
    (("reporting",), "flagged_amount_counting"),
])
def test_requires_nested_fields(tmp_path, policy, path, key):
    parent = policy
    for field in path:
        parent = parent[field]
    del parent[key]
    with pytest.raises(ValueError):
        load_policy(write_policy(tmp_path, policy))


def test_rejects_blank_category_key(tmp_path, policy):
    policy["categories"]["   "] = policy["categories"].pop("meals")
    with pytest.raises(ValueError):
        load_policy(write_policy(tmp_path, policy))


@pytest.mark.parametrize("value", [[], None, "policy", 1])
def test_requires_root_object(tmp_path, value):
    with pytest.raises(ValueError):
        load_policy(write_policy(tmp_path, value))


def test_json_and_file_errors(tmp_path):
    path = tmp_path / "policy.json"
    with pytest.raises(FileNotFoundError):
        load_policy(path)
    path.write_text('{"version":', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_policy(path)
    path.write_text('{"version":"1.0","version":"2.0"}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_policy(path)
    with pytest.raises(OSError):
        load_policy(tmp_path)


def test_loads_utf8_bom_and_preserves_unicode(tmp_path, policy):
    policy["name"] = "Travel policy for Chloë D’Souza"
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8-sig")
    assert load_policy(path) == policy


def test_rejects_invalid_utf8(tmp_path):
    path = tmp_path / "policy.json"
    path.write_bytes(b'{"name": "\xff"}')
    with pytest.raises(UnicodeDecodeError):
        load_policy(path)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_rejects_nonstandard_json_constants(tmp_path, policy, constant):
    # Write an unquoted constant into an otherwise valid policy.
    policy["categories"]["meals"]["max_amount"] = "RAW_CONSTANT"
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy).replace('"RAW_CONSTANT"', constant), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid JSON constant"):
        load_policy(path)


@pytest.mark.parametrize("mode", ["always", "unconfigured"])
def test_rejects_receipt_threshold_for_modes_that_do_not_use_it(tmp_path, policy, mode):
    policy["categories"]["meals"]["receipt"] = {"mode": mode, "threshold": "25.00"}
    with pytest.raises(ValueError, match="threshold: only valid for above_threshold mode"):
        load_policy(write_policy(tmp_path, policy))


def test_rejects_empty_categories(tmp_path, policy):
    policy["categories"] = {}
    with pytest.raises(ValueError, match="categories: expected a nonempty object"):
        load_policy(write_policy(tmp_path, policy))
