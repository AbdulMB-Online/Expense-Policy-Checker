"""Expense submission, review, ownership, and correction workflows."""

import json
from dataclasses import replace

from backend.database.errors import SubmissionConflictError
from backend.database.submissions import SubmissionStore
from backend.database.workspace import WorkspaceStore
from backend.services.errors import ServiceError
from backend.services.evaluation import load_report, with_submissions
from backend.services.reports import ReportService
from backend.services.uploads import UploadedFile
from backend.services.validation import parse_expense, read_receipt, validate_request_id


class ExpenseService:
    def __init__(
        self, reports: ReportService, submissions: SubmissionStore, workspace: WorkspaceStore
    ) -> None:
        self.reports = reports
        self.submissions = submissions
        self.workspace = workspace

    def submit(
        self,
        values: dict,
        request_id: str,
        dataset: str | None,
        receipt: UploadedFile | None,
        user: dict,
    ) -> dict:
        source = self.reports.resolve_source(dataset, user)
        if user["role"] == "employee" and values["employee"].strip() != user["name"]:
            raise ServiceError(403, "Submit expenses using your demo account identity.")
        key = validate_request_id(request_id)
        attachment = read_receipt(receipt)
        expense = parse_expense(values, source.policy, attachment is not None)
        owner = next(
            (
                item["id"]
                for item in self.workspace.sessions.users()
                if item["name"] == expense.employee
            ),
            None,
        )
        claim_id = self.submissions.save(
            source.submission_scope,
            key,
            expense,
            attachment,
            lambda records: load_report(with_submissions(source, records), None, ""),
            owner_id=owner,
            created_by=user["id"],
        )
        data = self.reports.serialize(source, None, "", dataset, user)
        return {
            "claim": next(claim for claim in data["submissions"] if claim["id"] == claim_id),
            "report": data,
        }

    def review(
        self,
        expense_id: str,
        run_id: str,
        revision_id: str,
        decision: str,
        comment: str,
        dataset: str | None,
        user: dict,
    ) -> dict:
        source = self.reports.resolve_source(dataset, user)
        current = self.reports.serialize(source, None, "", dataset, user)
        if run_id != current["run_id"]:
            raise SubmissionConflictError(
                "The checks changed. Refresh before reviewing this expense."
            )
        if decision != "approved" and not comment.strip():
            raise ServiceError(422, "Explain the rejection or requested changes.")
        self.workspace.reviews.review(
            source.submission_scope,
            expense_id,
            user,
            run_id,
            revision_id,
            decision,
            comment.strip(),
        )
        return self.reports.serialize(source, None, "", dataset, user)

    def map_owner(self, expense_id: str, owner_id: str, dataset: str | None, user: dict) -> dict:
        source = self.reports.resolve_source(dataset, user)
        self.reports.serialize(source, None, "", dataset, user)
        self.workspace.reviews.map_owner(source.submission_scope, expense_id, owner_id)
        return self.reports.serialize(source, None, "", dataset, user)

    def resubmit(
        self,
        expense_id: str,
        values: dict,
        revision: int,
        dataset: str | None,
        receipt: UploadedFile | None,
        user: dict,
    ) -> dict:
        source = self.reports.resolve_source(dataset, user)
        _, owner, record, _ = self.workspace.reviews.expense(
            source.submission_scope, expense_id, user
        )
        if owner != user["id"]:
            raise ServiceError(403, "Only the expense owner can resubmit it.")
        attachment = read_receipt(receipt)
        old = json.loads(record)
        expense = replace(
            parse_expense(
                {**values, "employee": user["name"]},
                source.policy,
                attachment is not None or old["receipt_attached"],
            ),
            id=expense_id,
        )
        self.workspace.reviews.resubmit(
            source.submission_scope,
            expense_id,
            user,
            expense,
            attachment,
            revision,
            lambda records: load_report(with_submissions(source, records), None, ""),
        )
        return self.reports.serialize(source, None, "", dataset, user)
