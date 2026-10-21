"""Load policy configuration and validate its schema, without evaluating expenses."""

import json
import re
from pathlib import Path

from .expense_loader import FIELDS


def _object(value, path, required, optional=()):
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    missing = set(required) - value.keys()
    unknown = value.keys() - set(required) - set(optional)
    if missing:
        raise ValueError(f"{path}: missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"{path}: unknown fields: {', '.join(sorted(unknown))}")


def _text(value, path):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: expected nonempty text")


def _boolean(value, path):
    if type(value) is not bool:
        raise ValueError(f"{path}: expected a boolean")


def _integer(value, path, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{path}: expected an integer >= {minimum}")


def _choice(value, path, choices):
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"{path}: expected one of {', '.join(choices)}")


def _money(value, path):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value):
        raise ValueError(
            f"{path}: expected a nonnegative decimal string with at most two decimal places"
        )


def _strings(value, path, *, allow_empty=True):
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ValueError(f"{path}: expected {'a' if allow_empty else 'a nonempty'} list")
    for item in value:
        _text(item, path)
    if len(set(value)) != len(value):
        raise ValueError(f"{path}: duplicate entries are not allowed")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate policy key: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


def load_policy(path: str | Path) -> dict:
    """Return validated JSON data. Money stays as strings; no expenses are checked.

    Raises ValueError (including JSONDecodeError) for invalid configuration and
    OSError for file access failures. Unknown fields are rejected to catch typos.
    """
    with Path(path).open(encoding="utf-8-sig") as source:
        policy = json.load(
            source, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
    _object(
        policy,
        "policy",
        (
            "version",
            "name",
            "currency",
            "categories",
            "restricted_categories",
            "unknown_category_action",
            "submission",
            "duplicates",
            "reporting",
        ),
    )
    for field in ("version", "name", "currency"):
        _text(policy[field], field)
    if not re.fullmatch(r"[A-Z]{3}", policy["currency"]):
        raise ValueError("currency: expected a three-letter uppercase currency code")
    categories = policy["categories"]
    if not isinstance(categories, dict) or not categories:
        raise ValueError("categories: expected a nonempty object")
    for category, settings in categories.items():
        _text(category, "categories key")
        prefix = f"categories.{category}"
        _object(
            settings,
            prefix,
            ("max_amount", "limit_basis", "receipt"),
            ("nights_required", "max_nights_per_stay", "review_required"),
        )
        if settings["max_amount"] is not None:
            _money(settings["max_amount"], f"{prefix}.max_amount")
        _choice(settings["limit_basis"], f"{prefix}.limit_basis", ("per_expense", "per_night"))
        receipt = settings["receipt"]
        _object(receipt, f"{prefix}.receipt", ("mode",), ("threshold",))
        mode = receipt["mode"]
        _choice(mode, f"{prefix}.receipt.mode", ("above_threshold", "always", "unconfigured"))
        if mode == "above_threshold":
            if "threshold" not in receipt:
                raise ValueError(f"{prefix}.receipt.threshold: required for above_threshold mode")
            _money(receipt["threshold"], f"{prefix}.receipt.threshold")
        elif "threshold" in receipt:
            raise ValueError(f"{prefix}.receipt.threshold: only valid for above_threshold mode")
        for field in ("nights_required", "review_required"):
            if field in settings:
                _boolean(settings[field], f"{prefix}.{field}")
        if settings.get("max_nights_per_stay") is not None:
            _integer(settings["max_nights_per_stay"], f"{prefix}.max_nights_per_stay", 1)
    _strings(policy["restricted_categories"], "restricted_categories")
    _choice(policy["unknown_category_action"], "unknown_category_action", ("review_required",))
    submission = policy["submission"]
    _object(submission, "submission", ("max_days_after_expense", "inclusive"))
    _integer(submission["max_days_after_expense"], "submission.max_days_after_expense")
    _boolean(submission["inclusive"], "submission.inclusive")
    duplicates = policy["duplicates"]
    _object(
        duplicates, "duplicates", ("key_fields", "require_different_ids", "flag", "classification")
    )
    _strings(duplicates["key_fields"], "duplicates.key_fields", allow_empty=False)
    if any(field not in FIELDS for field in duplicates["key_fields"]):
        raise ValueError("duplicates.key_fields: entries must be expense field names")
    _boolean(duplicates["require_different_ids"], "duplicates.require_different_ids")
    _choice(duplicates["flag"], "duplicates.flag", ("all_matches", "later_matches"))
    _choice(duplicates["classification"], "duplicates.classification", ("suspected_duplicate",))
    reporting = policy["reporting"]
    _object(reporting, "reporting", ("collect_all_violations", "flagged_amount_counting"))
    _boolean(reporting["collect_all_violations"], "reporting.collect_all_violations")
    _choice(
        reporting["flagged_amount_counting"],
        "reporting.flagged_amount_counting",
        ("once_per_expense",),
    )
    return policy
