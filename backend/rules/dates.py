"""Submission-deadline and future-date checks."""

from datetime import date

from .base import PolicyRule
from .helpers import _calendar_day


class SubmissionDeadlineRule(PolicyRule):
    """Flag a submission that is past ``submission.max_days_after_expense``.

    Elapsed time is the number of calendar days from the expense date to the
    submission date. ``inclusive`` true allows an elapsed time equal to the
    limit, so day 30 of a 30-day limit passes and day 31 fails. ``inclusive``
    false rejects an elapsed time equal to the limit. Missing or non-calendar
    dates produce no violation.
    """

    rule_id = "submission_deadline"
    rule_name = "Submission deadline"

    def evaluate(self, expense, all_expenses: list) -> str | None:
        submission = self.policy_data.get("submission")
        if not isinstance(submission, dict):
            return None
        limit = submission.get("max_days_after_expense")
        inclusive = submission.get("inclusive")
        if type(limit) is not int or type(inclusive) is not bool:
            return None
        expense_day = _calendar_day(getattr(expense, "date", None))
        submitted = _calendar_day(getattr(expense, "submission_date", None))
        if expense_day is None or submitted is None:
            return None
        elapsed = (submitted - expense_day).days
        late = elapsed > limit if inclusive else elapsed >= limit
        if not late:
            return None
        return f"Submitted {elapsed} days after the expense date, beyond the {limit}-day deadline."


class FutureExpenseDateRule(PolicyRule):
    """Flag an expense date after the configured reference date.

    The default reference is that expense's submission date, which keeps
    results independent of the machine clock. Pass ``reference_date`` to
    compare every expense with one calendar date instead. The expense date
    must be strictly later than the reference; the same day passes. Missing
    or non-calendar dates produce no violation.
    """

    rule_id = "future_expense_date"
    rule_name = "Future expense date"

    def __init__(self, policy_data: dict, *, reference_date: date | None = None):
        super().__init__(policy_data)
        self.reference_date = reference_date

    def evaluate(self, expense, all_expenses: list) -> str | None:
        expense_day = _calendar_day(getattr(expense, "date", None))
        if self.reference_date is None:
            reference = _calendar_day(getattr(expense, "submission_date", None))
            reference_name = "submission date"
        else:
            reference = _calendar_day(self.reference_date)
            reference_name = "reference date"
        if expense_day is None or reference is None:
            return None
        if expense_day <= reference:
            return None
        return (
            f"Expense date {expense_day.isoformat()} is after the "
            f"{reference_name} {reference.isoformat()}."
        )
