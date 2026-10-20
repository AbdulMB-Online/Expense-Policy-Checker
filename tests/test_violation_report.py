"""Verify reviewer-facing grouping, totals, and real sample integration."""

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from loader.expense_loader import Expense, LoadError, load_expenses
from loader.policy_loader import load_policy
from reporting.violation_report import build_report, group_report, render_report
from rules.base import PolicyViolation
from rules.engine import RulesEngine


ROOT = Path(__file__).resolve().parents[1]


def claim(expense_id="E-1", employee="Alice", amount="75.00"):
    return Expense(
        id=expense_id, employee=employee, date=date(2026, 10, 5),
        category="meals", amount=Decimal(amount), description="Team lunch",
        receipt_attached=False, submission_date=date(2026, 10, 5), nights=None,
    )


@pytest.fixture
def amount_violation():
    return PolicyViolation("amount_limit", "Amount limit", "Amount is above the meal limit.")


@pytest.fixture
def receipt_violation():
    return PolicyViolation("missing_receipt", "Missing receipt", "Required receipt is missing.")


def test_employee_groups_keep_all_reasons_and_count_each_claim_once(amount_violation, receipt_violation):
    expenses = [claim("E-1", "Zoe"), claim("E-2", "Alice", "0.10"), claim("E-3", "Zoe", "0.20")]
    report = build_report(expenses, {
        "E-1": [amount_violation, receipt_violation],
        "E-2": [receipt_violation],
        "E-3": [receipt_violation],
    }, currency="USD")
    assert report.total_expenses == report.flagged_count == 3
    assert report.violation_count == 4
    assert report.total_flagged_amount == Decimal("75.30")
    alice, zoe = group_report(report)
    assert [alice.name, zoe.name] == ["Alice", "Zoe"]
    assert alice.total_flagged_amount == Decimal("0.10")
    assert zoe.total_flagged_amount == Decimal("75.20")
    assert [item.expense.id for item in zoe.expenses] == ["E-1", "E-3"]
    assert zoe.expenses[0].violations == (amount_violation, receipt_violation)


def test_rule_groups_use_ids_and_show_only_the_matching_reasons():
    # Identical wording must not collapse different rules into the same group.
    first = PolicyViolation("first", "First check", "Needs review.")
    second = PolicyViolation("second", "Second check", "Needs review.")
    extra = PolicyViolation("first", "First check", "Another reason from the first rule.")
    report = build_report([claim()], {"E-1": [first, second, extra]}, currency="USD")
    first_group, second_group = group_report(report, group_by="rule")
    assert [first_group.key, second_group.key] == ["first", "second"]
    assert len(first_group.expenses) == len(second_group.expenses) == 1
    assert first_group.expenses[0].violations == (first, extra)
    assert second_group.expenses[0].violations == (second,)
    assert first_group.total_flagged_amount == second_group.total_flagged_amount == Decimal("75.00")
    assert report.total_flagged_amount == Decimal("75.00")
    assert report.flagged_count == 1
    assert report.violation_count == 3


def test_report_excludes_clean_claims_but_counts_accepted_inputs(receipt_violation):
    expenses = [claim("CLEAN-1"), claim("FLAGGED"), claim("CLEAN-2")]
    report = build_report(expenses, {"FLAGGED": [receipt_violation], "CLEAN-2": []}, currency="USD")
    assert report.total_expenses == 3
    assert report.flagged_count == 1
    assert [item.expense.id for item in report.flagged_expenses] == ["FLAGGED"]
    assert "CLEAN-1" not in render_report(report)
    assert "CLEAN-2" not in render_report(report)


@pytest.mark.parametrize("group_by", ["employee", "rule"])
@pytest.mark.parametrize("expenses", [[], [claim()]])
def test_no_flags_has_zero_totals_and_a_clear_empty_state(group_by, expenses):
    report = build_report(expenses, {}, currency="USD")
    assert report.flagged_count == report.violation_count == 0
    assert report.total_flagged_amount == Decimal("0.00")
    assert group_report(report, group_by=group_by) == ()
    text = render_report(report, group_by=group_by)
    assert "Flagged claims: 0" in text
    assert "Total flagged amount: USD 0.00" in text
    assert "No violations detected by the configured checks." in text


@pytest.mark.parametrize("group_by", ["employee", "rule"])
def test_loader_errors_stay_separate_and_retain_every_reason(group_by):
    errors = [
        LoadError(12, "BAD-1", ("employee is missing", "amount is negative")),
        LoadError(19, None, ("id is missing",)),
    ]
    report = build_report([], {}, currency="USD", errors=iter(errors))
    assert report.errors == tuple(errors)
    assert report.total_expenses == report.flagged_count == 0
    assert report.total_flagged_amount == Decimal("0.00")
    text = render_report(report, group_by=group_by)
    assert "Rejected rows: 2" in text
    assert "REJECTED INPUT ROWS: 2" in text
    assert "Line 12 | BAD-1" in text
    assert "Line 19 | ID unavailable" in text
    assert all(reason in text for error in errors for reason in error.reasons)


def test_report_is_an_immutable_snapshot_and_accepts_generators(receipt_violation):
    expenses = [claim()]
    results = {"E-1": [receipt_violation]}
    report = build_report(iter(expenses), results, currency="USD")
    results["E-1"].clear()
    expenses.clear()
    assert report.flagged_count == report.violation_count == 1
    assert report.flagged_expenses[0].violations == (receipt_violation,)
    with pytest.raises(FrozenInstanceError):
        report.currency = "EUR"


def test_totals_preserve_large_loader_valid_amounts_and_cents(receipt_violation):
    expenses = [claim("BIG", amount="999999999999999999999999999999.99"), claim("SMALL", amount="0.02")]
    report = build_report(expenses, {
        expense.id: [receipt_violation] for expense in expenses
    }, currency="USD")
    expected = Decimal("1000000000000000000000000000000.01")
    assert report.total_flagged_amount == expected
    assert group_report(report)[0].total_flagged_amount == expected
    assert f"Total flagged amount: USD {expected}" in render_report(report)


def test_zero_amount_can_be_flagged_without_changing_the_total(receipt_violation):
    report = build_report([claim(amount="0")], {"E-1": [receipt_violation]}, currency="USD")
    assert report.flagged_count == 1
    assert report.total_flagged_amount == Decimal("0.00")


def test_policy_currency_is_displayed_without_conversion(receipt_violation):
    report = build_report([claim()], {"E-1": [receipt_violation]}, currency="EUR")
    text = render_report(report)
    assert "Currency: EUR" in text
    assert "Total flagged amount: EUR 75.00" in text
    assert "USD" not in text


def test_employee_view_shows_claim_details_and_both_reasons(amount_violation, receipt_violation):
    report = build_report([claim()], {"E-1": [amount_violation, receipt_violation]}, currency="USD")
    text = render_report(report)
    assert "EMPLOYEE: Alice" in text
    assert "Flagged claims: 1 | Flagged amount: USD 75.00" in text
    assert "E-1 | 2026-10-05 | meals | USD 75.00" in text
    assert amount_violation.reason in text
    assert receipt_violation.reason in text
    assert "Violation reasons: 2" in text


def test_rule_view_includes_employee_and_explains_overlapping_totals(amount_violation, receipt_violation):
    report = build_report([claim()], {"E-1": [amount_violation, receipt_violation]}, currency="USD")
    text = render_report(report, group_by="rule")
    assert "RULE: Amount limit" in text
    assert "RULE: Missing receipt" in text
    assert text.count("E-1 | 2026-10-05 | Alice | meals | USD 75.00") == 2
    assert text.count(amount_violation.reason) == text.count(receipt_violation.reason) == 1
    assert "overall total counts each claim once" in text
    assert "Total flagged amount: USD 75.00" in text


@pytest.mark.parametrize("group_by", ["category", "", "EMPLOYEE"])
def test_invalid_group_choice_is_rejected_even_when_empty(group_by):
    report = build_report([], {}, currency="USD")
    with pytest.raises(ValueError, match="group_by"):
        render_report(report, group_by=group_by)


def test_duplicate_input_ids_cannot_inflate_totals(receipt_violation):
    with pytest.raises(ValueError, match="unique IDs"):
        build_report([claim(), claim()], {"E-1": [receipt_violation]}, currency="USD")


def test_unknown_result_ids_cannot_be_silently_discarded(receipt_violation):
    with pytest.raises(ValueError, match="unknown expense IDs: UNKNOWN"):
        build_report([claim()], {"UNKNOWN": [receipt_violation]}, currency="USD")


def test_real_sample_report_matches_planted_flags_and_exact_totals():
    loaded = load_expenses(ROOT / "data" / "expenses" / "sample_expenses.csv")
    policy = load_policy(ROOT / "data" / "policy" / "policy.json")
    detailed = RulesEngine(policy).run_detailed(loaded.expenses)
    report = build_report(loaded.expenses, detailed, currency=policy["currency"], errors=loaded.errors)
    assert report.total_expenses == 22
    assert len(report.errors) == 8
    assert report.flagged_count == 10
    assert report.violation_count == 12
    assert report.total_flagged_amount == Decimal("917.03")
    assert {item.expense.id for item in report.flagged_expenses} == {
        "EXP-003", "EXP-004", "EXP-005", "EXP-006", "EXP-007",
        "EXP-014", "EXP-016", "EXP-017", "EXP-019", "EXP-021",
    }
    employee_groups = group_report(report)
    assert [(group.name, len(group.expenses), group.total_flagged_amount) for group in employee_groups] == [
        ("Alice Morgan", 8, Decimal("837.03")),
        ("Jordan Lee", 2, Decimal("80.00")),
    ]
    rule_groups = group_report(report, group_by="rule")
    assert [(group.key, len(group.expenses), group.total_flagged_amount) for group in rule_groups] == [
        ("amount_limit", 6, Decimal("777.03")),
        ("missing_receipt", 4, Decimal("210.00")),
        ("suspected_duplicate", 2, Decimal("80.00")),
    ]
    for group_by in ("employee", "rule"):
        text = render_report(report, group_by=group_by)
        assert "Total flagged amount: USD 917.03" in text
        assert "REJECTED INPUT ROWS: 8" in text
        assert "EXP-002" not in text  # Meal exactly at the limit.
        assert "EXP-009" not in text  # No receipt, exactly at its threshold.
        assert "EXP-015" not in text  # Hotel exactly at the nightly limit.
        for violations in detailed.values():
            assert all(violation.reason in text for violation in violations)
