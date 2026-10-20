"""Tests for the policy rule classes.

An amount equal to the policy limit passes. When one expense breaks two
rules, ``RulesEngine.run_all`` keeps both violation messages.
"""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from loader.expense_loader import Expense, load_expenses
from loader.policy_loader import load_policy
from rules.base import PolicyRule, PolicyViolation
from rules.engine import (
    AmountLimitRule,
    DuplicateRule,
    FutureExpenseDateRule,
    MaxHotelStayRule,
    MissingHotelNightsRule,
    MissingReceiptRule,
    RestrictedCategoryRule,
    ReviewRequiredRule,
    RulesEngine,
    SubmissionDeadlineRule,
    UnknownCategoryRule,
)
from scripts.generate_example_policy import generate_policy


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
    assert [expense.id for expense in loaded.expenses] == [f"EXP-{number:03d}" for number in range(1, 73)]
    assert len(loaded.errors) == 28
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
        "Submitted 31 days after the expense date, beyond the 30-day deadline.",
    ]
    assert violations["EXP-016"] == ["Amount 402.00 exceeds the hotel limit of 200.00 per night for 2 nights."]
    assert violations["EXP-017"] == ["Receipt is missing for hotel expense 20.00."]
    assert "EXP-011" not in violations
    assert "EXP-044" not in violations
    assert "EXP-048" not in violations
    assert "EXP-056" not in violations
    assert violations["EXP-012"] == [
        "Submitted 31 days after the expense date, beyond the 30-day deadline."
    ]
    assert violations["EXP-013"] == ["Category alcohol is restricted."]
    assert violations["EXP-022"] == ["Category other requires review."]
    assert violations["EXP-047"] == ["Nights are required for hotel but none were provided."]
    assert violations["EXP-058"] == [
        "Expense date 2026-11-05 is after the submission date 2026-10-05."
    ]
    assert violations["EXP-062"] == [
        "Category training is unknown.",
        "Category training requires review.",
    ]
    assert violations["EXP-065"] == ["Category alcohol is restricted."]
    assert set(violations) == {
        "EXP-003", "EXP-004", "EXP-005", "EXP-006", "EXP-007",
        "EXP-012", "EXP-013", "EXP-014", "EXP-016", "EXP-017", "EXP-019", "EXP-021",
        "EXP-022", "EXP-025", "EXP-027", "EXP-028", "EXP-031", "EXP-033", "EXP-034",
        "EXP-037", "EXP-039", "EXP-040", "EXP-043", "EXP-045", "EXP-046", "EXP-047",
        "EXP-049", "EXP-050", "EXP-051", "EXP-052", "EXP-053", "EXP-054", "EXP-055",
        "EXP-057", "EXP-058", "EXP-061", "EXP-062", "EXP-063", "EXP-064", "EXP-065",
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


def test_existing_amount_receipt_and_duplicate_messages_stay_in_the_full_engine():
    over_limit = make_expense(id="E-5", amount=Decimal("75.00"), receipt_attached=False)
    duplicates = [
        make_expense(id="E-6", employee="Jordan", category="transport", amount=Decimal("40.00")),
        make_expense(id="E-7", employee="Jordan", category="transport", amount=Decimal("40.00")),
    ]
    engine = RulesEngine(make_policy())
    assert engine.run_all([over_limit]) == {
        "E-5": [
            "Amount 75.00 exceeds the meals limit of 50.00 per expense.",
            "Receipt is missing for meals expense 75.00, which is above the 25.00 threshold.",
        ],
    }
    assert engine.run_all(duplicates) == {
        "E-6": ["Duplicate of E-7 on employee, date, category, amount, nights."],
        "E-7": ["Duplicate of E-6 on employee, date, category, amount, nights."],
    }
    detailed = engine.run_detailed([over_limit])
    assert engine.run_all([over_limit]) == {
        expense_id: [item.reason for item in items] for expense_id, items in detailed.items()
    }


def test_engine_duplicate_matching_still_uses_configured_nights():
    same_stay = [
        make_expense(id="H-1", category="hotel", amount=Decimal("40.00"), nights=2),
        make_expense(id="H-2", category="hotel", amount=Decimal("40.00"), nights=2),
    ]
    different_stay = [
        same_stay[0],
        make_expense(id="H-3", category="hotel", amount=Decimal("40.00"), nights=3),
    ]
    policy = make_policy()
    assert RulesEngine(policy).run_all(same_stay)["H-1"] == [
        "Duplicate of H-2 on employee, date, category, amount, nights."
    ]
    assert RulesEngine(policy).run_all(different_stay) == {}
    policy["duplicates"]["key_fields"] = ["employee", "date", "amount", "category"]
    assert RulesEngine(policy).run_all(different_stay)["H-1"] == [
        "Duplicate of H-3 on employee, date, amount, category."
    ]


# Restricted, unknown, and review-required categories


def test_restricted_allowed_and_unknown_categories_are_distinct():
    policy = make_policy()
    restricted = RestrictedCategoryRule(policy)
    unknown = UnknownCategoryRule(policy)
    alcohol = make_expense(category="alcohol", amount=Decimal("15.00"))
    meals = make_expense(id="E-2")
    training = make_expense(id="E-3", category="training")
    assert restricted.evaluate(alcohol, [alcohol]) == "Category alcohol is restricted."
    assert unknown.evaluate(alcohol, [alcohol]) is None
    assert restricted.evaluate(meals, [meals]) is None
    assert unknown.evaluate(meals, [meals]) is None
    assert restricted.evaluate(training, [training]) is None
    assert unknown.evaluate(training, [training]) == "Category training is unknown."


def test_restricted_category_is_not_classified_as_unknown_or_review_required():
    alcohol = make_expense(category="alcohol", amount=Decimal("15.00"), receipt_attached=False)
    violations = RulesEngine(make_policy()).run_detailed([alcohol])["E-1"]
    assert violations == [
        PolicyViolation("restricted_category", "Restricted category", "Category alcohol is restricted."),
    ]


def test_unknown_category_action_controls_unknown_and_review_classification():
    training = make_expense(category="training", amount=Decimal("80.00"), receipt_attached=False)
    violations = RulesEngine(make_policy()).run_detailed([training])["E-1"]
    assert [item.rule_id for item in violations] == ["unknown_category", "review_required"]
    assert [item.reason for item in violations] == [
        "Category training is unknown.",
        "Category training requires review.",
    ]
    configured = make_policy()
    configured["unknown_category_action"] = "allow"
    assert RulesEngine(configured).run_all([training]) == {}


def test_review_required_follows_the_category_flag_only():
    other = make_expense(category="other", amount=Decimal("500.00"), receipt_attached=False)
    zero = make_expense(id="E-0", category="other", amount=Decimal("0.00"))
    meals = make_expense(id="E-2", amount=Decimal("75.00"), receipt_attached=False)
    engine = RulesEngine(make_policy())
    assert engine.run_detailed([other])["E-1"] == [
        PolicyViolation("review_required", "Review required", "Category other requires review."),
    ]
    assert engine.run_all([zero]) == {"E-0": ["Category other requires review."]}
    assert [item.rule_id for item in engine.run_detailed([meals])["E-2"]] == [
        "amount_limit", "missing_receipt",
    ]
    configured = make_policy()
    configured["categories"]["other"]["review_required"] = False
    assert ReviewRequiredRule(configured).evaluate(other, [other]) is None


def test_restricted_known_category_still_checks_its_amount_limit():
    configured = make_policy()
    configured["restricted_categories"] = ["meals"]
    expense = make_expense(amount=Decimal("75.00"))
    assert [item.rule_id for item in RulesEngine(configured).run_detailed([expense])["E-1"]] == [
        "amount_limit", "restricted_category",
    ]


# Submission deadline and future dates


def test_submission_deadline_accepts_day_29_and_inclusive_day_30():
    rule = SubmissionDeadlineRule(make_policy())
    day_29 = make_expense(date=date(2026, 9, 6), submission_date=date(2026, 10, 5))
    day_30 = make_expense(id="E-30", date=date(2026, 9, 5), submission_date=date(2026, 10, 5))
    day_31 = make_expense(id="E-31", date=date(2026, 9, 4), submission_date=date(2026, 10, 5))
    assert rule.evaluate(day_29, [day_29]) is None
    assert rule.evaluate(day_30, [day_30]) is None
    assert rule.evaluate(day_31, [day_31]) == (
        "Submitted 31 days after the expense date, beyond the 30-day deadline."
    )


def test_exclusive_deadline_rejects_the_exact_limit():
    configured = make_policy()
    configured["submission"]["inclusive"] = False
    rule = SubmissionDeadlineRule(configured)
    day_29 = make_expense(date=date(2026, 9, 6), submission_date=date(2026, 10, 5))
    day_30 = make_expense(id="E-30", date=date(2026, 9, 5), submission_date=date(2026, 10, 5))
    assert rule.evaluate(day_29, [day_29]) is None
    assert rule.evaluate(day_30, [day_30]) == (
        "Submitted 30 days after the expense date, beyond the 30-day deadline."
    )


def test_deadline_uses_calendar_days_across_leap_day_and_month_end():
    rule = SubmissionDeadlineRule(make_policy())
    leap = make_expense(date=date(2024, 2, 29), submission_date=date(2024, 3, 30))
    year_end = make_expense(id="E-2", date=date(2025, 12, 31), submission_date=date(2026, 1, 30))
    month_end = make_expense(id="E-3", date=date(2026, 1, 31), submission_date=date(2026, 3, 3))
    assert rule.evaluate(leap, [leap]) is None
    assert rule.evaluate(year_end, [year_end]) is None
    assert rule.evaluate(month_end, [month_end]) == (
        "Submitted 31 days after the expense date, beyond the 30-day deadline."
    )


@pytest.mark.parametrize("expense_date, submitted", [
    (None, date(2026, 10, 5)),
    (date(2026, 10, 5), None),
    ("2026-09-04", date(2026, 10, 5)),
    (datetime(2026, 9, 4), date(2026, 10, 5)),
    (date(2026, 9, 4), "2026-10-05"),
])
def test_deadline_and_future_checks_ignore_missing_or_invalid_dates(expense_date, submitted):
    expense = make_expense(date=expense_date, submission_date=submitted)
    assert SubmissionDeadlineRule(make_policy()).evaluate(expense, [expense]) is None
    assert FutureExpenseDateRule(make_policy()).evaluate(expense, [expense]) is None


def test_future_expense_dates_use_the_submission_date():
    rule = FutureExpenseDateRule(make_policy())
    past = make_expense(date=date(2020, 1, 1), submission_date=date(2020, 1, 2))
    same_day = make_expense(id="E-2", date=date(2020, 1, 2), submission_date=date(2020, 1, 2))
    future = make_expense(id="E-3", date=date(2020, 1, 3), submission_date=date(2020, 1, 2))
    assert rule.evaluate(past, [past]) is None
    assert rule.evaluate(same_day, [same_day]) is None
    assert rule.evaluate(future, [future]) == (
        "Expense date 2020-01-03 is after the submission date 2020-01-02."
    )


def test_future_expense_is_not_also_a_late_submission():
    expense = make_expense(date=date(2026, 11, 5), submission_date=date(2026, 10, 5))
    assert [item.rule_id for item in RulesEngine(make_policy()).run_detailed([expense])["E-1"]] == [
        "future_expense_date",
    ]


def test_injected_reference_date_replaces_the_submission_date():
    reference = date(2020, 1, 1)
    rule = FutureExpenseDateRule(make_policy(), reference_date=reference)
    before_reference = make_expense(date=date(2019, 12, 31), submission_date=date(2019, 1, 1))
    on_reference = make_expense(id="E-2", date=reference, submission_date=date(1999, 1, 1))
    after_reference = make_expense(id="E-3", date=date(2020, 1, 2), submission_date=date(2020, 1, 2))
    assert rule.evaluate(before_reference, [before_reference]) is None
    assert rule.evaluate(on_reference, [on_reference]) is None
    assert rule.evaluate(after_reference, [after_reference]) == (
        "Expense date 2020-01-02 is after the reference date 2020-01-01."
    )
    engine = RulesEngine(make_policy(), reference_date=reference)
    assert engine.run_all([before_reference]) == {}
    assert "reference date" in engine.run_all([after_reference])["E-3"][0]


def test_invalid_injected_reference_date_does_not_crash():
    expense = make_expense(date=date(2026, 10, 6), submission_date=date(2026, 10, 5))
    rule = FutureExpenseDateRule(make_policy(), reference_date="today")
    assert rule.evaluate(expense, [expense]) is None


# Hotel nights


@pytest.mark.parametrize("nights, expected", [
    (None, "Nights are required for hotel but none were provided."),
    (0, "Nights for hotel must be a positive integer."),
    (-1, "Nights for hotel must be a positive integer."),
    (True, "Nights for hotel must be a positive integer."),
    (False, "Nights for hotel must be a positive integer."),
    (1.5, "Nights for hotel must be a positive integer."),
    ("2", "Nights for hotel must be a positive integer."),
])
def test_required_hotel_nights_reject_missing_and_invalid_values(nights, expected):
    expense = make_expense(category="hotel", amount=Decimal("300.00"), nights=nights)
    assert MissingHotelNightsRule(make_policy()).evaluate(expense, [expense]) == expected


def test_valid_hotel_nights_and_unrequired_categories_pass():
    policy = make_policy()
    valid = make_expense(category="hotel", amount=Decimal("20.00"), nights=1)
    assert MissingHotelNightsRule(policy).evaluate(valid, [valid]) is None
    meals = make_expense(id="E-2", nights=None)
    invalid_meals = make_expense(id="E-3", nights=0)
    assert MissingHotelNightsRule(policy).evaluate(meals, [meals]) is None
    assert MissingHotelNightsRule(policy).evaluate(invalid_meals, [invalid_meals]) is None
    policy["categories"]["hotel"]["nights_required"] = False
    missing = make_expense(category="hotel", amount=Decimal("20.00"), nights=None)
    assert MissingHotelNightsRule(policy).evaluate(missing, [missing]) is None


def test_maximum_stay_checks_below_at_and_above_the_limit():
    configured = make_policy()
    configured["categories"]["hotel"]["max_nights_per_stay"] = 7
    rule = MaxHotelStayRule(configured)
    below = make_expense(category="hotel", amount=Decimal("10.00"), nights=6)
    at_limit = make_expense(id="E-2", category="hotel", amount=Decimal("10.00"), nights=7)
    above = make_expense(id="E-3", category="hotel", amount=Decimal("10.00"), nights=8)
    assert rule.evaluate(below, [below]) is None
    assert rule.evaluate(at_limit, [at_limit]) is None
    assert rule.evaluate(above, [above]) == (
        "Stay of 8 nights exceeds the hotel maximum of 7 nights."
    )


def test_null_or_missing_maximum_stay_is_not_invented():
    long_stay = make_expense(category="hotel", amount=Decimal("10.00"), nights=100)
    assert MaxHotelStayRule(make_policy()).evaluate(long_stay, [long_stay]) is None
    configured = make_policy()
    del configured["categories"]["hotel"]["max_nights_per_stay"]
    assert MaxHotelStayRule(configured).evaluate(long_stay, [long_stay]) is None


@pytest.mark.parametrize("nights", [None, 0, -3, "8", True, 1.5])
def test_maximum_stay_ignores_missing_and_invalid_nights(nights):
    configured = make_policy()
    configured["categories"]["hotel"]["max_nights_per_stay"] = 7
    expense = make_expense(category="hotel", amount=Decimal("10.00"), nights=nights)
    assert MaxHotelStayRule(configured).evaluate(expense, [expense]) is None


def test_sample_hotel_stay_respects_null_and_configured_maximums(tmp_path):
    loaded = load_expenses(ROOT / "data" / "expenses" / "sample_expenses.csv")
    standard = RulesEngine(load_policy(ROOT / "data" / "policy" / "policy.json"))
    assert "EXP-044" not in standard.run_all(loaded.expenses)
    assert "EXP-048" not in standard.run_all(loaded.expenses)
    travel = load_policy(generate_policy(tmp_path / "business_travel.json"))
    assert RulesEngine(travel).run_detailed(loaded.expenses)["EXP-048"] == [
        PolicyViolation(
            "max_hotel_stay",
            "Maximum hotel stay",
            "Stay of 8 nights exceeds the hotel maximum of 7 nights.",
        ),
    ]
    assert "EXP-044" not in RulesEngine(travel).run_all(loaded.expenses)


# Several rules on one expense, ordering, and empty input


def test_one_expense_keeps_every_applicable_violation_in_rule_order():
    configured = make_policy()
    configured["categories"]["meals"]["review_required"] = True
    expense = make_expense(
        amount=Decimal("75.00"),
        receipt_attached=False,
        date=date(2026, 9, 4),
        submission_date=date(2026, 10, 5),
    )
    violations = RulesEngine(configured).run_detailed([expense])["E-1"]
    assert [item.rule_id for item in violations] == [
        "amount_limit", "missing_receipt", "submission_deadline", "review_required",
    ]
    hotel_policy = make_policy()
    hotel_policy["categories"]["hotel"]["max_nights_per_stay"] = 2
    hotel = make_expense(
        id="H-1", category="hotel", amount=Decimal("1000.00"), nights=3, receipt_attached=False,
    )
    assert [item.rule_id for item in RulesEngine(hotel_policy).run_detailed([hotel])["H-1"]] == [
        "amount_limit", "missing_receipt", "max_hotel_stay",
    ]


def test_collect_all_false_keeps_only_the_first_violation():
    configured = make_policy()
    configured["reporting"]["collect_all_violations"] = False
    expense = make_expense(
        amount=Decimal("75.00"),
        receipt_attached=False,
        date=date(2026, 9, 4),
        submission_date=date(2026, 10, 5),
    )
    assert RulesEngine(configured).run_all([expense]) == {
        "E-1": ["Amount 75.00 exceeds the meals limit of 50.00 per expense."],
    }


def test_missing_collect_all_flag_still_keeps_every_violation():
    configured = make_policy()
    del configured["reporting"]
    expense = make_expense(amount=Decimal("75.00"), receipt_attached=False)
    assert RulesEngine(configured).run_all([expense])["E-1"] == [
        "Amount 75.00 exceeds the meals limit of 50.00 per expense.",
        "Receipt is missing for meals expense 75.00, which is above the 25.00 threshold.",
    ]


def test_empty_input_and_clean_expenses_produce_no_results():
    engine = RulesEngine(make_policy())
    assert engine.run_all([]) == {}
    assert engine.run_detailed([]) == {}
    assert engine.run_all([make_expense()]) == {}
    assert engine.run_detailed([make_expense(amount=Decimal("50.00"))]) == {}


def test_results_keep_expense_order_and_both_result_formats_match():
    expenses = [
        make_expense(id="CLEAN"),
        make_expense(id="LATE", date=date(2026, 9, 4), submission_date=date(2026, 10, 5)),
        make_expense(id="ALCOHOL", category="alcohol", amount=Decimal("15.00")),
        make_expense(id="OVER", amount=Decimal("75.00"), receipt_attached=False),
    ]
    engine = RulesEngine(make_policy())
    detailed = engine.run_detailed(iter(expenses))
    assert list(detailed) == ["LATE", "ALCOHOL", "OVER"]
    assert [item.rule_id for item in detailed["OVER"]] == ["amount_limit", "missing_receipt"]
    assert engine.run_all(expenses) == {
        expense_id: [item.reason for item in items] for expense_id, items in detailed.items()
    }
