"""Shared interface for policy rules."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyViolation:
    """A rule's identity and its original explanation for a flagged expense."""

    rule_id: str
    rule_name: str
    reason: str


class PolicyRule(ABC):
    """One policy check.

    ``evaluate`` returns a violation message, or ``None`` when the expense
    passes. An amount equal to its category limit passes. When one expense
    breaks more than one rule, each rule still returns its own message and
    ``RulesEngine.run_all`` keeps every message.

    Rules may define ``rule_id`` and ``rule_name`` for detailed reports.
    Otherwise the engine uses the rule's class name for both.
    """

    def __init__(self, policy_data: dict):
        self.policy_data = policy_data

    @abstractmethod
    def evaluate(self, expense, all_expenses: list) -> str | None:
        """Return a violation message, or None when this rule passes."""
