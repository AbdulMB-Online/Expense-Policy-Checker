"""Policy checks for validated expenses.

A category in ``restricted_categories`` with no ``categories`` entry is both
restricted and unknown. The engine reports both findings. ``other`` is a
configured category, so it requires review and is not unknown.
"""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from loader.expense_loader import Expense, load_expenses
from loader.policy_loader import load_policy
from rules.engine import evaluate_expenses


ROOT = Path(__file__).resolve().parents[1]
INCURRED = date(2026, 10, 1)


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
            "office_supplies": {
                "max_amount": "100.00",
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


def rule_names(findings):
    return tuple(finding.rule for finding in findings)


def names_for(result, expense_id):
    for item in result.results:
        if item.expense_id == expense_id:
            return rule_names(item.findings)
    raise AssertionError(expense_id)


# Amount limits


def test_per_expense_limit_reads_the_policy_and_allows_the_exact_amount():
    configured = make_policy()
    configured["categories"]["meals"]["max_amount"] = "10.50"
    expenses = [
        make_expense(id="E-1", amount=Decimal("10.50")),
        make_expense(id="E-2", amount=Decimal("10.51")),
        make_expense(id="E-3", amount=Decimal("0.00")),
    ]
    result = evaluate_expenses(expenses, configured)
    assert names_for(result, "E-1") == ()
    assert names_for(result, "E-3") == ()
    finding = result.results[1].findings[0]
    assert (finding.rule, finding.classification) == ("amount_limit", "violation")
    assert finding.expense_id == "E-2"
    assert finding.explanation == "Amount 10.51 exceeds the meals limit of 10.50 per expense."
    assert configured["categories"]["meals"]["max_amount"] == "10.50"


def test_null_maximum_has_no_amount_limit():
    item = make_expense(category="other", amount=Decimal("500.00"), receipt_attached=False)
    result = evaluate_expenses([item], make_policy())
    assert rule_names(result.results[0].findings) == ("review_required",)


def test_per_expense_compares_the_full_amount_when_nights_are_present():
    configured = make_policy()
    configured["categories"]["hotel"]["limit_basis"] = "per_expense"
    configured["categories"]["hotel"]["max_amount"] = "30.00"
    expenses = [
        make_expense(id="E-1", category="hotel", amount=Decimal("30.00"), nights=2, receipt_attached=True),
        make_expense(id="E-2", category="hotel", amount=Decimal("30.01"), nights=2, receipt_attached=True),
    ]
    result = evaluate_expenses(expenses, configured)
    assert names_for(result, "E-1") == ()
    assert names_for(result, "E-2") == ("amount_limit",)


def test_nightly_limit_allows_the_exact_stay_total():
    configured = make_policy()
    configured["categories"]["hotel"]["max_amount"] = "15.00"
    expenses = [
        make_expense(id="E-1", category="hotel", amount=Decimal("30.00"), nights=2, receipt_attached=True),
        make_expense(id="E-2", category="hotel", amount=Decimal("30.01"), nights=2, receipt_attached=True),
        make_expense(id="E-3", category="hotel", amount=Decimal("15.00"), nights=1, receipt_attached=True),
        make_expense(id="E-4", category="hotel", amount=Decimal("15.01"), nights=1, receipt_attached=True),
    ]
    result = evaluate_expenses(expenses, configured)
    assert names_for(result, "E-1") == ()
    assert names_for(result, "E-3") == ()
    over_two = result.results[1].findings[0]
    assert over_two.explanation == (
        "Amount 30.01 exceeds the hotel limit of 15.00 per night for 2 nights (stay limit 30.00)."
    )
    assert result.results[3].findings[0].explanation == (
        "Amount 15.01 exceeds the hotel limit of 15.00 per night for 1 night (stay limit 15.00)."
    )


@pytest.mark.parametrize("nights", [None, 0, -1])
def test_nightly_limit_does_not_divide_by_missing_or_invalid_nights(nights):
    configured = make_policy()
    configured["categories"]["hotel"]["max_amount"] = "15.00"
    item = make_expense(
        category="hotel", amount=Decimal("999.00"), nights=nights, receipt_attached=True,
    )
    result = evaluate_expenses([item], configured)
    assert "amount_limit" not in rule_names(result.results[0].findings)
    expected = "missing_nights" if nights is None else "invalid_nights"
    assert rule_names(result.results[0].findings) == (expected,)


# Receipts


@pytest.mark.parametrize("amount, attached, expected", [
    ("4.00", False, ()),
    ("4.01", False, ("receipt_required",)),
    ("4.01", True, ()),
    ("10.00", False, ("receipt_required",)),
])
def test_receipt_above_threshold_is_strict_and_reads_the_policy(amount, attached, expected):
    configured = make_policy()
    configured["categories"]["meals"]["receipt"] = {"mode": "above_threshold", "threshold": "4.00"}
    item = make_expense(amount=Decimal(amount), receipt_attached=attached)
    result = evaluate_expenses([item], configured)
    assert rule_names(result.results[0].findings) == expected


def test_receipt_explanation_uses_the_threshold_and_amount():
    configured = make_policy()
    configured["categories"]["transport"]["receipt"]["threshold"] = "25.00"
    item = make_expense(
        category="transport", amount=Decimal("40.00"), receipt_attached=False,
    )
    finding = evaluate_expenses([item], configured).results[0].findings[0]
    assert finding.rule == "receipt_required"
    assert finding.classification == "violation"
    assert finding.explanation == (
        "A receipt is required for transport expenses above 25.00; the amount is 40.00."
    )


def test_receipt_always_required_at_any_amount():
    missing = make_expense(
        id="E-1", category="hotel", amount=Decimal("20.00"), nights=1, receipt_attached=False,
    )
    present = make_expense(
        id="E-2", category="hotel", amount=Decimal("0.00"), nights=1, receipt_attached=True,
    )
    result = evaluate_expenses([missing, present], make_policy())
    assert names_for(result, "E-2") == ()
    finding = result.results[0].findings[0]
    assert finding.explanation == "A receipt is required for every hotel expense."


def test_unconfigured_receipt_mode_creates_no_receipt_finding():
    item = make_expense(category="other", amount=Decimal("500.00"), receipt_attached=False)
    assert rule_names(evaluate_expenses([item], make_policy()).results[0].findings) == ("review_required",)


# Categories


def test_restricted_category_is_flagged():
    item = make_expense(category="alcohol", amount=Decimal("15.00"), receipt_attached=True)
    finding = evaluate_expenses([item], make_policy()).results[0].findings[0]
    assert finding.rule == "restricted_category"
    assert finding.classification == "violation"
    assert finding.explanation == "Category alcohol is restricted."


def test_unknown_category_uses_the_policy_action():
    configured = make_policy()
    item = make_expense(category="gadgets", amount=Decimal("15.00"), receipt_attached=True)
    finding = evaluate_expenses([item], configured).results[0].findings[0]
    assert finding.rule == "unknown_category"
    assert finding.classification == configured["unknown_category_action"]
    assert finding.explanation == (
        "Category gadgets is outside the configured categories; "
        "the policy action is review_required."
    )


def test_other_is_review_required_and_not_unknown():
    item = make_expense(category="other", amount=Decimal("500.00"), receipt_attached=False)
    findings = evaluate_expenses([item], make_policy()).results[0].findings
    assert [(finding.rule, finding.classification) for finding in findings] == [
        ("review_required", "review_required"),
    ]
    assert findings[0].explanation == "Category other requires review."


def test_restricted_and_unknown_category_reports_both_findings():
    """Alcohol is restricted and absent from categories, so both rules apply."""
    item = make_expense(category="alcohol", amount=Decimal("15.00"), receipt_attached=True)
    findings = evaluate_expenses([item], make_policy()).results[0].findings
    assert [(finding.rule, finding.classification, finding.explanation) for finding in findings] == [
        ("restricted_category", "violation", "Category alcohol is restricted."),
        (
            "unknown_category",
            "review_required",
            "Category alcohol is outside the configured categories; the policy action is review_required.",
        ),
    ]


def test_restricted_configured_category_keeps_its_limits_and_is_not_unknown():
    configured = make_policy()
    configured["restricted_categories"] = ["meals"]
    item = make_expense(amount=Decimal("50.01"), receipt_attached=True)
    assert rule_names(evaluate_expenses([item], configured).results[0].findings) == (
        "restricted_category", "amount_limit",
    )


def test_review_required_false_creates_no_review_finding():
    configured = make_policy()
    configured["categories"]["meals"]["review_required"] = False
    item = make_expense(amount=Decimal("20.00"))
    assert evaluate_expenses([item], configured).results[0].findings == ()


def test_category_match_is_exact():
    item = make_expense(category="Alcohol", amount=Decimal("15.00"), receipt_attached=True)
    assert rule_names(evaluate_expenses([item], make_policy()).results[0].findings) == ("unknown_category",)


# Submission deadlines


def test_inclusive_day_30_passes_and_day_31_fails():
    configured = make_policy()
    configured["submission"]["max_days_after_expense"] = 30
    configured["submission"]["inclusive"] = True
    expenses = [
        make_expense(id="E-1", date=INCURRED, submission_date=INCURRED + timedelta(days=30)),
        make_expense(
            id="E-2", amount=Decimal("21.00"), date=INCURRED,
            submission_date=INCURRED + timedelta(days=31),
        ),
    ]
    result = evaluate_expenses(expenses, configured)
    assert names_for(result, "E-1") == ()
    finding = result.results[1].findings[0]
    assert finding.explanation == "Submitted 31 days after the expense; the limit is 30 days, inclusive."


def test_submission_before_the_expense_date_is_allowed():
    configured = make_policy()
    configured["submission"] = {"max_days_after_expense": 0, "inclusive": True}
    expenses = [
        make_expense(id="E-1", date=INCURRED, submission_date=INCURRED - timedelta(days=1)),
        make_expense(id="E-2", amount=Decimal("21.00"), date=INCURRED, submission_date=INCURRED),
        make_expense(
            id="E-3", amount=Decimal("22.00"), date=INCURRED,
            submission_date=INCURRED + timedelta(days=1),
        ),
    ]
    result = evaluate_expenses(expenses, configured)
    assert names_for(result, "E-1") == ()
    assert names_for(result, "E-2") == ()
    assert names_for(result, "E-3") == ("submission_deadline",)


def test_exclusive_deadline_rejects_the_boundary_day():
    configured = make_policy()
    configured["submission"] = {"max_days_after_expense": 10, "inclusive": False}
    expenses = [
        make_expense(id="E-1", date=INCURRED, submission_date=INCURRED + timedelta(days=9)),
        make_expense(
            id="E-2", amount=Decimal("21.00"), date=INCURRED,
            submission_date=INCURRED + timedelta(days=10),
        ),
    ]
    result = evaluate_expenses(expenses, configured)
    assert names_for(result, "E-1") == ()
    assert result.results[1].findings[0].explanation == (
        "Submitted 10 days after the expense; the limit is 10 days, exclusive."
    )


def test_submission_window_comes_from_the_policy():
    configured = make_policy()
    configured["submission"] = {"max_days_after_expense": 2, "inclusive": True}
    expenses = [
        make_expense(id="E-1", date=INCURRED, submission_date=INCURRED + timedelta(days=2)),
        make_expense(
            id="E-2", amount=Decimal("21.00"), date=INCURRED,
            submission_date=INCURRED + timedelta(days=3),
        ),
    ]
    result = evaluate_expenses(expenses, configured)
    assert names_for(result, "E-1") == ()
    assert names_for(result, "E-2") == ("submission_deadline",)


# Duplicates


def test_all_matches_flags_every_record_in_the_group():
    configured = make_policy()
    configured["duplicates"]["classification"] = "possible_duplicate"
    expenses = [
        make_expense(id="E-1", amount=Decimal("10.00")),
        make_expense(id="E-2", amount=Decimal("10.00")),
        make_expense(id="E-3", amount=Decimal("10.00")),
    ]
    result = evaluate_expenses(expenses, configured)
    assert [rule_names(item.findings) for item in result.results] == [
        ("duplicate",), ("duplicate",), ("duplicate",),
    ]
    assert result.results[0].findings[0].classification == "possible_duplicate"
    assert result.results[0].findings[0].explanation == (
        "Same employee, date, category, amount, nights as E-2, E-3."
    )
    assert result.flagged_amount == Decimal("30.00")


def test_later_matches_flags_every_record_after_the_first():
    configured = make_policy()
    configured["duplicates"]["flag"] = "later_matches"
    expenses = [
        make_expense(id="E-1", amount=Decimal("10.00")),
        make_expense(id="E-2", amount=Decimal("10.00")),
        make_expense(id="E-3", amount=Decimal("10.00")),
    ]
    result = evaluate_expenses(expenses, configured)
    assert [rule_names(item.findings) for item in result.results] == [(), ("duplicate",), ("duplicate",)]
    assert result.results[1].findings[0].explanation == (
        "Same employee, date, category, amount, nights as E-1, E-3."
    )
    assert result.flagged_amount == Decimal("20.00")


def test_duplicate_key_uses_configured_fields():
    configured = make_policy()
    configured["duplicates"]["key_fields"] = ["employee"]
    expenses = [
        make_expense(id="E-1", amount=Decimal("10.00"), description="Lunch"),
        make_expense(id="E-2", amount=Decimal("12.00"), description="Dinner"),
        make_expense(id="E-3", amount=Decimal("10.00"), employee="Jordan"),
    ]
    result = evaluate_expenses(expenses, configured)
    assert names_for(result, "E-1") == ("duplicate",)
    assert names_for(result, "E-2") == ("duplicate",)
    assert names_for(result, "E-3") == ()


def test_duplicate_matching_uses_dates_decimals_and_optional_nights():
    configured = make_policy()
    configured["duplicates"]["key_fields"] = ["date", "amount", "nights"]
    expenses = [
        make_expense(id="E-1", amount=Decimal("40.00"), nights=None, date=date(2026, 10, 5)),
        make_expense(id="E-2", amount=Decimal("40.0"), nights=None, date=date(2026, 10, 5)),
        make_expense(id="E-3", amount=Decimal("40.00"), nights=None, date=date(2026, 10, 6)),
        make_expense(id="E-4", amount=Decimal("41.00"), nights=2, date=date(2026, 10, 5)),
    ]
    result = evaluate_expenses(expenses, configured)
    assert names_for(result, "E-1") == ("duplicate",)
    assert names_for(result, "E-2") == ("duplicate",)
    assert names_for(result, "E-3") == ()
    assert names_for(result, "E-4") == ()
    assert result.results[0].findings[0].explanation == "Same date, amount, nights as E-2."


def test_same_id_follows_require_different_ids():
    same_id = [
        make_expense(id="E-1", amount=Decimal("10.00")),
        make_expense(id="E-1", amount=Decimal("10.00")),
    ]
    required = make_policy()
    skipped = evaluate_expenses(same_id, required)
    assert [rule_names(item.findings) for item in skipped.results] == [(), ()]
    required["duplicates"]["require_different_ids"] = False
    matched = evaluate_expenses(same_id, required)
    assert [rule_names(item.findings) for item in matched.results] == [("duplicate",), ("duplicate",)]


# Hotel nights


def test_missing_required_nights():
    item = make_expense(category="hotel", amount=Decimal("20.00"), nights=None, receipt_attached=True)
    finding = evaluate_expenses([item], make_policy()).results[0].findings[0]
    assert finding.rule == "missing_nights"
    assert finding.explanation == "Category hotel requires a number of nights."


def test_max_nights_allows_the_exact_stay_and_flags_one_more():
    configured = make_policy()
    configured["categories"]["hotel"]["max_nights_per_stay"] = 3
    configured["categories"]["hotel"]["max_amount"] = "15.00"
    expenses = [
        make_expense(id="E-1", category="hotel", amount=Decimal("45.00"), nights=3, receipt_attached=True),
        make_expense(id="E-2", category="hotel", amount=Decimal("40.00"), nights=4, receipt_attached=True),
    ]
    result = evaluate_expenses(expenses, configured)
    assert names_for(result, "E-1") == ()
    assert result.results[1].findings[0].explanation == (
        "Stay of 4 nights exceeds the hotel maximum of 3 nights."
    )


def test_null_max_nights_does_not_cap_the_stay():
    item = make_expense(
        category="hotel", amount=Decimal("2000.00"), nights=10, receipt_attached=True,
    )
    assert evaluate_expenses([item], make_policy()).results[0].findings == ()


def test_night_cap_and_nightly_amount_can_both_apply():
    configured = make_policy()
    configured["categories"]["hotel"]["max_nights_per_stay"] = 3
    configured["categories"]["hotel"]["max_amount"] = "15.00"
    item = make_expense(
        category="hotel", amount=Decimal("100.00"), nights=4, receipt_attached=True,
    )
    result = evaluate_expenses([item], configured)
    assert rule_names(result.results[0].findings) == ("max_nights_per_stay", "amount_limit")
    assert result.flagged_amount == Decimal("100.00")


def test_invalid_nights_explanation():
    item = make_expense(category="hotel", amount=Decimal("20.00"), nights=0, receipt_attached=True)
    finding = evaluate_expenses([item], make_policy()).results[0].findings[0]
    assert finding.explanation == "Category hotel requires a positive number of nights; received 0."


# Reporting


def test_multiple_findings_count_the_expense_amount_once():
    item = make_expense(
        amount=Decimal("75.00"),
        receipt_attached=False,
        date=INCURRED,
        submission_date=INCURRED + timedelta(days=31),
    )
    result = evaluate_expenses([item], make_policy())
    assert rule_names(result.results[0].findings) == (
        "amount_limit", "receipt_required", "submission_deadline",
    )
    assert result.flagged_amount == Decimal("75.00")
    assert type(result.flagged_amount) is Decimal


def test_results_preserve_input_order_and_sum_flagged_amounts():
    expenses = [
        make_expense(id="E-1", amount=Decimal("10.00")),
        make_expense(id="E-2", amount=Decimal("50.01")),
        make_expense(
            id="E-3", amount=Decimal("20.00"), date=INCURRED,
            submission_date=INCURRED + timedelta(days=31),
        ),
    ]
    result = evaluate_expenses(expenses, make_policy())
    assert [item.expense_id for item in result.results] == ["E-1", "E-2", "E-3"]
    assert [len(item.findings) for item in result.results] == [0, 1, 1]
    assert result.flagged_amount == Decimal("70.01")


def test_collect_all_false_keeps_the_first_finding_and_duplicates():
    configured = make_policy()
    configured["reporting"]["collect_all_violations"] = False
    alcohol = make_expense(id="E-9", category="alcohol", amount=Decimal("15.00"), receipt_attached=True)
    assert rule_names(evaluate_expenses([alcohol], configured).results[0].findings) == ("restricted_category",)
    pair = [
        make_expense(id="E-1", amount=Decimal("75.00"), receipt_attached=False),
        make_expense(id="E-2", amount=Decimal("75.00"), receipt_attached=False),
    ]
    result = evaluate_expenses(pair, configured)
    assert [rule_names(item.findings) for item in result.results] == [
        ("amount_limit", "duplicate"),
        ("amount_limit", "duplicate"),
    ]
    assert result.flagged_amount == Decimal("150.00")


def test_empty_batch_has_a_zero_decimal_total():
    result = evaluate_expenses([], make_policy())
    assert result.results == ()
    assert result.flagged_amount == Decimal("0.00")
    assert type(result.flagged_amount) is Decimal


def test_policy_money_strings_are_not_replaced():
    configured = make_policy()
    evaluate_expenses([make_expense(amount=Decimal("80.00"), receipt_attached=False)], configured)
    assert configured["categories"]["meals"]["max_amount"] == "50.00"
    assert type(configured["categories"]["meals"]["receipt"]["threshold"]) is str


# Checked-in sample


def test_checked_in_sample_and_policy():
    loaded = load_expenses(ROOT / "data" / "expenses" / "sample_expenses.csv")
    configured = load_policy(ROOT / "data" / "policy" / "policy.json")
    assert [expense.id for expense in loaded.expenses] == [
        f"EXP-{number:03d}" for number in range(1, 23)
    ]
    assert [(error.line_number, error.expense_id) for error in loaded.errors] == [
        (12, "BAD-001"),
        (13, "BAD-002"),
        (14, "BAD-003"),
        (15, "BAD-004"),
        (16, "BAD-005"),
        (17, "BAD-006"),
        (18, None),
        (19, "EXP-001"),
    ]
    evaluation = evaluate_expenses(loaded.expenses, configured)
    assert [item.expense_id for item in evaluation.results] == [expense.id for expense in loaded.expenses]
    expected = {
        "EXP-001": (),
        "EXP-002": (),
        "EXP-003": (("amount_limit", "violation"),),
        "EXP-004": (("receipt_required", "violation"),),
        "EXP-005": (("amount_limit", "violation"), ("receipt_required", "violation")),
        "EXP-006": (("duplicate", "suspected_duplicate"),),
        "EXP-007": (("duplicate", "suspected_duplicate"),),
        "EXP-008": (),
        "EXP-009": (),
        "EXP-010": (),
        "EXP-011": (),
        "EXP-012": (("submission_deadline", "violation"),),
        "EXP-013": (
            ("restricted_category", "violation"),
            ("unknown_category", "review_required"),
        ),
        "EXP-014": (
            ("amount_limit", "violation"),
            ("receipt_required", "violation"),
            ("submission_deadline", "violation"),
        ),
        "EXP-015": (),
        "EXP-016": (("amount_limit", "violation"),),
        "EXP-017": (("receipt_required", "violation"),),
        "EXP-018": (),
        "EXP-019": (("amount_limit", "violation"),),
        "EXP-020": (),
        "EXP-021": (("amount_limit", "violation"),),
        "EXP-022": (("review_required", "review_required"),),
    }
    assert set(expected) == {expense.id for expense in loaded.expenses}
    for item in evaluation.results:
        pairs = tuple((finding.rule, finding.classification) for finding in item.findings)
        assert pairs == expected[item.expense_id]
    by_id = {item.expense_id: item for item in evaluation.results}
    assert "EXP-007" in by_id["EXP-006"].findings[0].explanation
    assert "EXP-006" in by_id["EXP-007"].findings[0].explanation
    assert "402.00" in by_id["EXP-016"].findings[0].explanation
    assert "200.00" in by_id["EXP-016"].findings[0].explanation
    flagged_ids = {expense_id for expense_id, pairs in expected.items() if pairs}
    total = sum(
        (expense.amount for expense in loaded.expenses if expense.id in flagged_ids),
        Decimal("0.00"),
    )
    assert evaluation.flagged_amount == total
    assert type(evaluation.flagged_amount) is Decimal
    assert configured["categories"]["meals"]["max_amount"] == "50.00"
