"""Tests for the policy rule classes.

An amount equal to the policy limit passes. When one expense breaks two
rules, ``RulesEngine.run_all`` keeps both violation messages.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from loader.expense_loader import Expense, load_expenses
from loader.policy_loader import load_policy
from rules.base import PolicyRule, PolicyViolation
from rules.engine import AmountLimitRule, DuplicateRule, MissingReceiptRule, RulesEngine


ROOT = Path(__file__).resolve().parents[1]


def make_expense(**overrides):
    values = {
        "id": "E-1",
        "employee": "Alice",
        "date": date(2026, 10, 5),
        "category": "meals",
        "amount": Decimal("20.00"),
        "description": "Team lunch",
        "receipt_attached": True,
        "submission_date": date(2026, 10, 5),
        "nights": None,
    }
    values.update(overrides)
    return Expense(**values)


def make_policy():
    return {
        "version": "1.0",
        "name": "Test policy",
        "currency": "USD",
        "categories": {
            "meals": {
                "max_amount": "50.00",
                "limit_basis": "per_expense",
                "receipt": {"mode": "above_threshold", "threshold": "25.00"},
            },
            "hotel": {
                "max_amount": "200.00",
                "limit_basis": "per_night",
                "receipt": {"mode": "always"},
                "nights_required": True,
                "max_nights_per_stay": None,
            },
            "transport": {
                "max_amount": "75.00",
                "limit_basis": "per_expense",
                "receipt": {"mode": "above_threshold", "threshold": "25.00"},
            },
            "other": {
                "max_amount": None,
                "limit_basis": "per_expense",
                "receipt": {"mode": "unconfigured"},
                "review_required": True,
            },
        },
        "restricted_categories": ["alcohol"],
        "unknown_category_action": "review_required",
        "submission": {"max_days_after_expense": 30, "inclusive": True},
        "duplicates": {
            "key_fields": ["employee", "date", "category", "amount", "nights"],
            "require_different_ids": True,
            "flag": "all_matches",
            "classification": "suspected_duplicate",
        },
        "reporting": {
            "collect_all_violations": True,
            "flagged_amount_counting": "once_per_expense",
        },
    }


def test_policy_rule_cannot_be_instantiated():
    with pytest.raises(TypeError):
        PolicyRule({})


# AmountLimitRule


def test_amount_exactly_equal_to_the_limit_passes():
    configured = make_policy()
    configured["categories"]["meals"]["max_amount"] = "10.50"
    rule = AmountLimitRule(configured)
    at_limit = make_expense(amount=Decimal("10.50"))
    one_cent_over = make_expense(id="E-2", amount=Decimal("10.51"))
    assert rule.evaluate(at_limit, [at_limit]) is None
    assert rule.evaluate(one_cent_over, [one_cent_over]) == (
        "Amount 10.51 exceeds the meals limit of 10.50 per expense."
    )


@pytest.mark.parametrize("amount", ["0.00", "10.49", "10.50"])
def test_amount_at_or_below_the_limit_passes(amount):
    configured = make_policy()
    configured["categories"]["meals"]["max_amount"] = "10.50"
    expense = make_expense(amount=Decimal(amount))
    assert AmountLimitRule(configured).evaluate(expense, [expense]) is None


def test_null_maximum_and_unknown_category_have_no_amount_violation():
    rule = AmountLimitRule(make_policy())
    other = make_expense(category="other", amount=Decimal("500.00"))
    unknown = make_expense(id="E-2", category="gadgets", amount=Decimal("500.00"))
    assert rule.evaluate(other, [other]) is None
    assert rule.evaluate(unknown, [unknown]) is None


def test_per_expense_compares_the_full_amount_when_nights_are_present():
    configured = make_policy()
    configured["categories"]["hotel"]["limit_basis"] = "per_expense"
    configured["categories"]["hotel"]["max_amount"] = "30.00"
    at_limit = make_expense(category="hotel", amount=Decimal("30.00"), nights=2)
    over = make_expense(id="E-2", category="hotel", amount=Decimal("30.01"), nights=2)
    rule = AmountLimitRule(configured)
    assert rule.evaluate(at_limit, [at_limit]) is None
    assert rule.evaluate(over, [over]) == (
        "Amount 30.01 exceeds the hotel limit of 30.00 per expense."
    )


def test_nightly_amount_exactly_at_the_stay_limit_passes():
    configured = make_policy()
    configured["categories"]["hotel"]["max_amount"] = "15.00"
    rule = AmountLimitRule(configured)
    two_nights = make_expense(category="hotel", amount=Decimal("30.00"), nights=2)
    one_night = make_expense(id="E-2", category="hotel", amount=Decimal("15.00"), nights=1)
    over = make_expense(id="E-3", category="hotel", amount=Decimal("30.01"), nights=2)
    assert rule.evaluate(two_nights, [two_nights]) is None
    assert rule.evaluate(one_night, [one_night]) is None
    assert rule.evaluate(over, [over]) == (
        "Amount 30.01 exceeds the hotel limit of 15.00 per night for 2 nights."
    )


@pytest.mark.parametrize("nights", [None, 0, -1])
def test_nightly_limit_does_not_divide_by_missing_or_invalid_nights(nights):
    configured = make_policy()
    configured["categories"]["hotel"]["max_amount"] = "15.00"
    expense = make_expense(category="hotel", amount=Decimal("999.00"), nights=nights)
    assert AmountLimitRule(configured).evaluate(expense, [expense]) is None


def test_amount_limit_reads_the_checked_in_policy_file():
    policy = load_policy(ROOT / "data" / "policy" / "policy.json")
    rule = AmountLimitRule(policy)
    at_limit = make_expense(amount=Decimal("50.00"))
    over = make_expense(id="E-2", amount=Decimal("50.01"))
    assert rule.evaluate(at_limit, [at_limit]) is None
    assert rule.evaluate(over, [over]) == (
        "Amount 50.01 exceeds the meals limit of 50.00 per expense."
    )
    assert policy["categories"]["meals"]["max_amount"] == "50.00"


# MissingReceiptRule


@pytest.mark.parametrize("amount, attached, expected", [
    ("4.00", False, None),
    ("4.01", False, "Receipt is missing for meals expense 4.01, which is above the 4.00 threshold."),
    ("4.01", True, None),
])
def test_receipt_is_required_only_above_the_threshold(amount, attached, expected):
    configured = make_policy()
    configured["categories"]["meals"]["receipt"] = {"mode": "above_threshold", "threshold": "4.00"}
    expense = make_expense(amount=Decimal(amount), receipt_attached=attached)
    assert MissingReceiptRule(configured).evaluate(expense, [expense]) == expected


def test_receipt_always_required_and_unconfigured_mode():
    rule = MissingReceiptRule(make_policy())
    missing = make_expense(category="hotel", amount=Decimal("20.00"), nights=1, receipt_attached=False)
    present = make_expense(id="E-2", category="hotel", amount=Decimal("20.00"), nights=1, receipt_attached=True)
    other = make_expense(id="E-3", category="other", amount=Decimal("500.00"), receipt_attached=False)
    assert rule.evaluate(missing, [missing]) == "Receipt is missing for hotel expense 20.00."
    assert rule.evaluate(present, [present]) is None
    assert rule.evaluate(other, [other]) is None


def test_unknown_category_has_no_receipt_violation():
    expense = make_expense(category="gadgets", amount=Decimal("80.00"), receipt_attached=False)
    assert MissingReceiptRule(make_policy()).evaluate(expense, [expense]) is None


# DuplicateRule


def test_all_matches_flags_every_duplicate_on_employee_date_amount_and_category():
    configured = make_policy()
    expenses = [
        make_expense(id="E-1", amount=Decimal("40.00")),
        make_expense(id="E-2", amount=Decimal("40.0")),
        make_expense(id="E-3", amount=Decimal("40.00"), category="transport"),
        make_expense(id="E-4", amount=Decimal("40.00"), employee="Jordan"),
        make_expense(id="E-5", amount=Decimal("41.00")),
        make_expense(id="E-6", amount=Decimal("40.00"), date=date(2026, 10, 6)),
    ]
    rule = DuplicateRule(configured)
    assert rule.evaluate(expenses[0], expenses) == (
        "Duplicate of E-2 on employee, date, category, amount, nights."
    )
    assert rule.evaluate(expenses[1], expenses) == (
        "Duplicate of E-1 on employee, date, category, amount, nights."
    )
    assert rule.evaluate(expenses[2], expenses) is None
    assert rule.evaluate(expenses[3], expenses) is None
    assert rule.evaluate(expenses[4], expenses) is None
    assert rule.evaluate(expenses[5], expenses) is None


def test_later_matches_leaves_the_first_record_unflagged():
    configured = make_policy()
    configured["duplicates"]["flag"] = "later_matches"
    expenses = [
        make_expense(id="E-1", amount=Decimal("10.00")),
        make_expense(id="E-2", amount=Decimal("10.00")),
        make_expense(id="E-3", amount=Decimal("10.00")),
    ]
    rule = DuplicateRule(configured)
    assert rule.evaluate(expenses[0], expenses) is None
    assert rule.evaluate(expenses[1], expenses) == (
        "Duplicate of E-1, E-3 on employee, date, category, amount, nights."
    )
    assert rule.evaluate(expenses[2], expenses) == (
        "Duplicate of E-1, E-2 on employee, date, category, amount, nights."
    )


def test_duplicate_key_uses_configured_fields():
    configured = make_policy()
    configured["duplicates"]["key_fields"] = ["employee"]
    expenses = [
        make_expense(id="E-1", amount=Decimal("10.00")),
        make_expense(id="E-2", amount=Decimal("12.00")),
        make_expense(id="E-3", amount=Decimal("10.00"), employee="Jordan"),
    ]
    rule = DuplicateRule(configured)
    assert rule.evaluate(expenses[0], expenses) == "Duplicate of E-2 on employee."
    assert rule.evaluate(expenses[2], expenses) is None


def test_nights_is_compared_only_when_listed_in_key_fields():
    expenses = [
        make_expense(id="E-1", category="hotel", amount=Decimal("40.00"), nights=1),
        make_expense(id="E-2", category="hotel", amount=Decimal("40.00"), nights=2),
    ]
    assert DuplicateRule(make_policy()).evaluate(expenses[0], expenses) is None
    configured = make_policy()
    configured["duplicates"]["key_fields"] = ["employee", "date", "amount", "category"]
    assert DuplicateRule(configured).evaluate(expenses[0], expenses) == (
        "Duplicate of E-2 on employee, date, amount, category."
    )


def test_same_id_follows_require_different_ids():
    expenses = [
        make_expense(id="E-1", amount=Decimal("10.00")),
        make_expense(id="E-1", amount=Decimal("10.00")),
    ]
    required = make_policy()
    assert DuplicateRule(required).evaluate(expenses[0], expenses) is None
    required["duplicates"]["require_different_ids"] = False
    assert DuplicateRule(required).evaluate(expenses[0], expenses) == (
        "Duplicate of E-1 on employee, date, category, amount, nights."
    )


# RulesEngine


def test_run_all_collects_every_violation_when_two_rules_break():
    expense = make_expense(id="E-5", amount=Decimal("75.00"), receipt_attached=False)
    violations = RulesEngine(make_policy()).run_all([expense])
    assert violations == {
        "E-5": [
            "Amount 75.00 exceeds the meals limit of 50.00 per expense.",
            "Receipt is missing for meals expense 75.00, which is above the 25.00 threshold.",
        ],
    }


def test_run_all_omits_clean_expenses_and_keeps_input_order():
    expenses = [
        make_expense(id="E-1", amount=Decimal("50.00")),
        make_expense(id="E-2", amount=Decimal("50.01")),
        make_expense(id="E-3", amount=Decimal("10.00")),
    ]
    violations = RulesEngine(make_policy()).run_all(expenses)
    assert list(violations) == ["E-2"]
    assert len(violations["E-2"]) == 1


def test_run_all_maps_duplicate_violations_by_expense_id():
    expenses = [
        make_expense(id="E-6", employee="Jordan", category="transport", amount=Decimal("40.00")),
        make_expense(id="E-7", employee="Jordan", category="transport", amount=Decimal("40.00")),
    ]
    violations = RulesEngine(make_policy()).run_all(expenses)
    assert set(violations) == {"E-6", "E-7"}
    assert violations["E-6"] == ["Duplicate of E-7 on employee, date, category, amount, nights."]
    assert violations["E-7"] == ["Duplicate of E-6 on employee, date, category, amount, nights."]


def test_checked_in_sample_collects_amount_receipt_and_duplicate_violations():
    loaded = load_expenses(ROOT / "data" / "expenses" / "sample_expenses.csv")
    policy = load_policy(ROOT / "data" / "policy" / "policy.json")
    violations = RulesEngine(policy).run_all(loaded.expenses)
    assert [expense.id for expense in loaded.expenses] == [f"EXP-{number:03d}" for number in range(1, 23)]
    assert len(loaded.errors) == 8
    assert "EXP-002" not in violations
    assert "EXP-009" not in violations
    assert "EXP-015" not in violations
    assert violations["EXP-003"] == ["Amount 50.01 exceeds the meals limit of 50.00 per expense."]
    assert violations["EXP-005"] == [
        "Amount 75.00 exceeds the meals limit of 50.00 per expense.",
        "Receipt is missing for meals expense 75.00, which is above the 25.00 threshold.",
    ]
    assert violations["EXP-006"] == [
        "Duplicate of EXP-007 on employee, date, category, amount, nights."
    ]
    assert violations["EXP-014"] == [
        "Amount 75.00 exceeds the meals limit of 50.00 per expense.",
        "Receipt is missing for meals expense 75.00, which is above the 25.00 threshold.",
    ]
    assert violations["EXP-016"] == ["Amount 402.00 exceeds the hotel limit of 200.00 per night for 2 nights."]
    assert violations["EXP-017"] == ["Receipt is missing for hotel expense 20.00."]
    assert set(violations) == {
        "EXP-003", "EXP-004", "EXP-005", "EXP-006", "EXP-007",
        "EXP-014", "EXP-016", "EXP-017", "EXP-019", "EXP-021",
    }


def test_detailed_results_identify_rules_and_preserve_legacy_messages():
    expenses = [
        make_expense(id="CLEAN"),
        make_expense(id="FLAGGED", amount=Decimal("75.00"), receipt_attached=False),
    ]
    engine = RulesEngine(make_policy())
    detailed = engine.run_detailed(iter(expenses))
    assert list(detailed) == ["FLAGGED"]
    assert detailed["FLAGGED"] == [
        PolicyViolation("amount_limit", "Amount limit", "Amount 75.00 exceeds the meals limit of 50.00 per expense."),
        PolicyViolation("missing_receipt", "Missing receipt",
                        "Receipt is missing for meals expense 75.00, which is above the 25.00 threshold."),
    ]
    assert engine.run_all(expenses) == {
        expense_id: [item.reason for item in items]
        for expense_id, items in detailed.items()
    }


def test_detailed_results_support_new_rules_without_message_classification():
    class CustomRule(PolicyRule):
        def evaluate(self, expense, all_expenses):
            return "A custom review reason."

    class NamedRule(PolicyRule):
        rule_id = "named_check"
        rule_name = "Named check"

        def evaluate(self, expense, all_expenses):
            return "A custom review reason."

    engine = RulesEngine(make_policy())
    engine.rules = [CustomRule({}), NamedRule({})]
    assert engine.run_detailed([make_expense()]) == {
        "E-1": [
            PolicyViolation("CustomRule", "CustomRule", "A custom review reason."),
            PolicyViolation("named_check", "Named check", "A custom review reason."),
        ],
    }
