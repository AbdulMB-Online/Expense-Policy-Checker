"""Coordinate snapshots, visibility, report presentation, and exports."""

import csv
import json
from dataclasses import asdict, replace
from decimal import DecimalException
from secrets import token_urlsafe

from backend.config import ENGINE_VERSION
from backend.database.errors import RecordNotFoundError
from backend.database.policies import policy_record
from backend.database.serialization import expense_from_record
from backend.database.submissions import SubmissionStore
from backend.database.workspace import WorkspaceStore
from backend.loader.expense_loader import FIELDS, LoadResult
from backend.reporting.violation_report import build_report, group_report, render_report
from backend.rules.base import PolicyViolation
from backend.rules.engine import RulesEngine
from backend.services.errors import ServiceError
from backend.services.evaluation import load_report, with_submissions
from backend.services.report_views import claim_view, report_summary
from backend.services.sources import ReportSource, SourceStore
from backend.services.uploads import UploadedFile


class ReportService:
    def __init__(
        self, sources: SourceStore, submissions: SubmissionStore, workspace: WorkspaceStore
    ) -> None:
        self.sources = sources
        self.submissions = submissions
        self.workspace = workspace

    def resolve_source(self, dataset: str | None, user: dict) -> ReportSource:
        source = self.sources.resolve(dataset)
        if (
            dataset
            and user["role"] != "reviewer"
            and not any(item["id"] == dataset for item in self.workspace.datasets.datasets(user))
        ):
            raise RecordNotFoundError("Dataset not found.")
        return source

    def serialize(
        self,
        source: ReportSource,
        employee: str | None,
        search: str,
        dataset: str | None,
        user: dict,
    ) -> dict:
        snapshot_id = dataset or self.sources.snapshot(source)
        saved = {item.expense.id: item for item in self.submissions.list(source.submission_scope)}
        source = with_submissions(source, tuple(item.expense for item in saved.values()))
        try:
            run_id, generated_at, findings, metadata = self.workspace.checks.evaluate(
                source.submission_scope,
                source.policy,
                source.loaded.expenses,
                [asdict(error) for error in source.loaded.errors],
                ENGINE_VERSION,
                lambda: RulesEngine(source.policy).run_detailed(source.loaded.expenses),
                snapshot_id,
            )
        except (ValueError, csv.Error, DecimalException) as error:
            raise ServiceError(
                503,
                "Unable to prepare the report. Check the stored expense CSV and policy JSON, then retry.",
            ) from error
        violations = {
            key: [PolicyViolation(**value) for value in values] for key, values in findings.items()
        }
        if user["role"] != "reviewer":
            visible = tuple(
                item
                for item in source.loaded.expenses
                if metadata[item.id]["owner_id"] == user["id"]
            )
            # Duplicate detection retains company context; employees receive no
            # other employees' claim IDs or rejected source rows.
            violations = {
                item.id: [
                    replace(
                        reason,
                        reason="Possible duplicate detected. A reviewer will check the matching records.",
                    )
                    if reason.rule_id == "suspected_duplicate"
                    else reason
                    for reason in violations.get(item.id, [])
                ]
                for item in visible
            }
            source = replace(source, loaded=LoadResult(visible, ()))
            saved = {
                key: value
                for key, value in saved.items()
                if metadata[key]["owner_id"] == user["id"]
            }
        evaluation = load_report(source, employee, search, violations)
        loaded, policy = source.loaded, source.policy

        def claim(expense, reasons):
            return {**claim_view(expense, reasons, saved, dataset), **metadata[expense.id]}

        groups = {}
        for grouping in ("employee", "rule"):
            groups[grouping] = [
                {
                    "id": group.key,
                    "name": group.name,
                    "total_amount": f"{group.total_flagged_amount:.2f}",
                    "claims": [claim(item.expense, item.violations) for item in group.expenses],
                }
                for group in group_report(evaluation.report, group_by=grouping)
            ]
        dates = [expense.date for expense in loaded.expenses]
        return {
            "generated_at": generated_at,
            "run_id": run_id,
            "current_user": user,
            "dataset_id": dataset,
            "currency": policy["currency"],
            "sources": {"expenses": source.expense_name, "policy": source.policy_name},
            "period": {"start": min(dates).isoformat(), "end": max(dates).isoformat()}
            if dates
            else None,
            "overview": report_summary(evaluation.overview),
            "summary": report_summary(evaluation.report),
            "employees": evaluation.employees,
            "claims": [
                claim(expense, violations.get(expense.id, [])) for expense in evaluation.selected
            ],
            "submissions": [
                claim(item.expense, violations.get(item.expense.id, [])) for item in saved.values()
            ],
            "groups": groups,
            "errors": [asdict(error) for error in loaded.errors],
            "policy": {
                "id": policy_record(policy)["id"],
                "name": policy["name"],
                "version": policy["version"],
                "categories": policy["categories"],
                "active_rules": [
                    getattr(rule, "rule_name", type(rule).__name__)
                    for rule in evaluation.engine.rules
                ],
            },
        }

    def upload(
        self,
        expenses: UploadedFile | None,
        policy: UploadedFile | None,
        dataset: str | None,
        user: dict,
    ) -> dict:
        source = self.sources.prepare(expenses, policy, dataset)
        # Validate the full input before retaining a snapshot.
        token = token_urlsafe(24)
        previous = self.submissions.list(source.submission_scope)
        load_report(with_submissions(source, tuple(item.expense for item in previous)), None, "")
        self.sources.save(source, token, user["id"])
        return self.serialize(source, None, "", token, user)

    def export(
        self, group_by: str, employee: str | None, search: str, dataset: str | None, user: dict
    ) -> tuple[str, str]:
        source = self.resolve_source(dataset, user)
        data = self.serialize(source, employee, search, dataset, user)
        # Export the same immutable values shown in this report, even if another
        # request corrects an expense while the download is being prepared.
        selected = tuple(
            expense_from_record(json.dumps({field: claim[field] for field in FIELDS}))
            for claim in data["claims"]
        )
        findings = {
            claim["id"]: [PolicyViolation(**item) for item in claim["violations"]]
            for claim in data["claims"]
        }
        report = build_report(
            selected,
            findings,
            currency=source.policy["currency"],
            errors=source.loaded.errors if user["role"] == "reviewer" else (),
        )
        contents = render_report(report, group_by=group_by)
        artifact_id = self.workspace.artifacts.save_export(
            data["run_id"],
            user["id"],
            f"expense-report-{group_by}.txt",
            contents.encode(),
            {"employee": employee, "search": search, "group_by": group_by, "dataset": dataset},
        )
        return contents, artifact_id
