"""Per-application dependencies and shared authentication guards."""

from dataclasses import dataclass
from pathlib import Path

from fastapi import Cookie, Depends, HTTPException, Request

from backend.database.errors import AccessError
from backend.database.submissions import SubmissionStore
from backend.database.workspace import WorkspaceStore
from backend.services.expenses import ExpenseService
from backend.services.reports import ReportService
from backend.services.sources import SourceStore


@dataclass(frozen=True)
class Services:
    workspace: WorkspaceStore
    submissions: SubmissionStore
    reports: ReportService
    expenses: ExpenseService

    @classmethod
    def create(cls, root: Path) -> "Services":
        workspace = WorkspaceStore(root)
        submissions = SubmissionStore(root)
        sources = SourceStore(root, workspace)
        reports = ReportService(sources, submissions, workspace)
        return cls(workspace, submissions, reports, ExpenseService(reports, submissions, workspace))


def get_services(request: Request) -> Services:
    return request.app.state.services


def current_user(
    expense_session: str | None = Cookie(default=None),
    services: Services = Depends(get_services),
) -> dict:
    try:
        return services.workspace.sessions.session(expense_session)
    except AccessError as error:
        raise HTTPException(401, str(error)) from error


def reviewer(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "reviewer":
        raise HTTPException(403, "A reviewer account is required.")
    return user
