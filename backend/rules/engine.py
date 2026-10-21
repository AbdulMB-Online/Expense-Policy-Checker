"""Run policy rules against validated expenses.

Policy money stays in ``Decimal``. An amount equal to the configured limit
passes. When ``reporting.collect_all_violations`` is true, ``RulesEngine.run_all``
keeps every violation for an expense. Future expense dates are compared with
each claim's submission date unless a reference date is injected.
"""

from datetime import date

from .amount_limit import AmountLimitRule
from .base import PolicyRule as PolicyRule
from .base import PolicyViolation
from .categories import (
    RestrictedCategoryRule,
    ReviewRequiredRule,
    UnknownCategoryRule,
)
from .categories import (
    _known_or_restricted as _known_or_restricted,
)
from .dates import FutureExpenseDateRule, SubmissionDeadlineRule
from .duplicates import DuplicateRule
from .duplicates import _same_duplicate_key as _same_duplicate_key
from .helpers import _calendar_day as _calendar_day
from .helpers import _category_settings as _category_settings
from .helpers import _decimal_money as _decimal_money
from .helpers import _money_text as _money_text
from .hotel import MaxHotelStayRule, MissingHotelNightsRule
from .missing_receipt import MissingReceiptRule

# PolicyRule and the private helpers remain importable from this module.


class RulesEngine:
    """Apply every rule and collect violations by expense id."""

    def __init__(self, policy_data: dict, *, reference_date: date | None = None):
        self.policy_data = policy_data
        self.reference_date = reference_date
        self.rules = [
            AmountLimitRule(policy_data),
            MissingReceiptRule(policy_data),
            DuplicateRule(policy_data),
            RestrictedCategoryRule(policy_data),
            UnknownCategoryRule(policy_data),
            SubmissionDeadlineRule(policy_data),
            FutureExpenseDateRule(policy_data, reference_date=reference_date),
            MissingHotelNightsRule(policy_data),
            MaxHotelStayRule(policy_data),
            ReviewRequiredRule(policy_data),
        ]

    def run_all(self, expenses) -> dict[str, list[str]]:
        """Return each violating expense id mapped to every violation message.

        An expense that breaks two rules appears once, with both messages.
        An amount exactly at its limit is not a violation. Expenses with no
        violations are omitted.
        """
        return {
            expense_id: [violation.reason for violation in violations]
            for expense_id, violations in self.run_detailed(expenses).items()
        }

    def run_detailed(self, expenses) -> dict[str, list[PolicyViolation]]:
        """Keep rule identities alongside reasons, without parsing message text.

        Like ``run_all``, omit clean expenses and preserve expense/rule order.
        Each rule is evaluated once per expense. New rules can supply stable
        ``rule_id`` and ``rule_name`` attributes; class names are the fallback.
        ``reporting.collect_all_violations`` false keeps the first violation
        in rule order. A missing flag still collects every violation.
        """
        expense_list = list(expenses)
        reporting = (
            self.policy_data.get("reporting") if isinstance(self.policy_data, dict) else None
        )
        collect_all = not (
            isinstance(reporting, dict) and reporting.get("collect_all_violations") is False
        )
        violations: dict[str, list[PolicyViolation]] = {}
        for expense in expense_list:
            messages = []
            for rule in self.rules:
                message = rule.evaluate(expense, expense_list)
                if message is not None:
                    messages.append(
                        PolicyViolation(
                            rule_id=getattr(rule, "rule_id", type(rule).__name__),
                            rule_name=getattr(rule, "rule_name", type(rule).__name__),
                            reason=message,
                        )
                    )
                    if not collect_all:
                        break
            if messages:
                violations.setdefault(expense.id, []).extend(messages)
        return violations
