"""Stable dashboard representations for expense reports."""

from dataclasses import asdict
from urllib.parse import urlencode

from backend.loader.expense_loader import Expense
from backend.reporting.violation_report import ViolationReport


def report_summary(report: ViolationReport) -> dict:
    return {
        "accepted_count": report.total_expenses,
        "unflagged_count": report.total_expenses - report.flagged_count,
        "flagged_count": report.flagged_count,
        "violation_count": report.violation_count,
        "rejected_count": len(report.errors),
        "total_flagged_amount": f"{report.total_flagged_amount:.2f}",
    }


def claim_view(
    expense: Expense, violations: list | tuple, saved: dict, dataset: str | None
) -> dict:
    submission = saved.get(expense.id)
    receipt_url = f"/api/receipts/{expense.id}" + (
        "?" + urlencode({"dataset": dataset}) if dataset else ""
    )
    return {
        "id": expense.id,
        "employee": expense.employee,
        "date": expense.date.isoformat(),
        "category": expense.category,
        "amount": f"{expense.amount:.2f}",
        "description": expense.description,
        "receipt_attached": expense.receipt_attached,
        "submission_date": expense.submission_date.isoformat(),
        "nights": expense.nights,
        "origin": "submission" if submission else "file",
        "receipt": {"name": submission.receipt_name, "download_url": receipt_url}
        if submission and submission.receipt_name
        else None,
        "status": "flagged" if violations else "unflagged",
        "violations": [asdict(violation) for violation in violations],
    }
