"""Expose the existing expense pipeline to React without duplicating rules."""

import csv
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import DecimalException
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Form, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from api.sources import ReportSource, SourceStore
from loader.expense_loader import Expense
from reporting.violation_report import ViolationReport, build_report, group_report, render_report
from rules.engine import RulesEngine


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _summary(report: ViolationReport) -> dict:
    return {
        "accepted_count": report.total_expenses,
        "unflagged_count": report.total_expenses - report.flagged_count,
        "flagged_count": report.flagged_count,
        "violation_count": report.violation_count,
        "rejected_count": len(report.errors),
        "total_flagged_amount": f"{report.total_flagged_amount:.2f}",
    }


def _claim(expense: Expense, violations: list | tuple) -> dict:
    return {
        "id": expense.id,
        "employee": expense.employee,
        "date": expense.date.isoformat(),
        "category": expense.category,
        "amount": f"{expense.amount:.2f}",
        "description": expense.description,
        "receipt_attached": expense.receipt_attached,
        "status": "flagged" if violations else "unflagged",
        "violations": [asdict(violation) for violation in violations],
    }


def _load(source: ReportSource, employee: str | None, search: str):
    loaded, policy = source.loaded, source.policy
    try:
        engine = RulesEngine(policy)
        violations = engine.run_detailed(loaded.expenses)
    except (OSError, ValueError, csv.Error, DecimalException) as error:
        raise HTTPException(
            status_code=503,
            detail="Unable to prepare the report. Check the stored expense CSV and policy JSON, then retry.",
        ) from error

    employees = sorted({expense.employee for expense in loaded.expenses})
    if employee and employee not in employees:
        raise HTTPException(status_code=422, detail="Choose an employee from the report.")

    # Evaluate the complete input before filtering: duplicate context must survive
    # employee and search filters, including custom duplicate-key configurations.
    query = search.strip().casefold()
    selected = tuple(
        expense for expense in loaded.expenses
        if (not employee or expense.employee == employee)
        and (not query or query in " ".join((
            expense.id, expense.employee, expense.date.isoformat(),
            expense.category, expense.description,
        )).casefold())
    )
    selected_ids = {expense.id for expense in selected}
    selected_violations = {key: value for key, value in violations.items() if key in selected_ids}
    all_report = build_report(loaded.expenses, violations, currency=policy["currency"], errors=loaded.errors)
    report = build_report(selected, selected_violations, currency=policy["currency"], errors=loaded.errors)
    return loaded, policy, employees, violations, selected, engine, all_report, report


def create_app(project_root: Path | None = None) -> FastAPI:
    """Create an app for the real project or an isolated fixture directory."""
    root = Path(project_root) if project_root is not None else PROJECT_ROOT
    application = FastAPI(title="Expense Policy Checker", version="1.0.0")
    sources = SourceStore(root)

    @application.get("/api/health")
    def health():
        return {"status": "ok"}

    def serialize(source: ReportSource, employee: str | None, search: str, dataset: str | None):
        loaded, policy, employees, violations, selected, engine, all_report, report = _load(source, employee, search)
        groups = {}
        for grouping in ("employee", "rule"):
            groups[grouping] = [
                {
                    "id": group.key,
                    "name": group.name,
                    "total_amount": f"{group.total_flagged_amount:.2f}",
                    "claims": [_claim(item.expense, item.violations) for item in group.expenses],
                }
                for group in group_report(report, group_by=grouping)
            ]
        dates = [expense.date for expense in loaded.expenses]
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dataset_id": dataset,
            "currency": policy["currency"],
            "sources": {"expenses": source.expense_name, "policy": source.policy_name},
            "period": {"start": min(dates).isoformat(), "end": max(dates).isoformat()} if dates else None,
            "overview": _summary(all_report),
            "summary": _summary(report),
            "employees": employees,
            "claims": [_claim(expense, violations.get(expense.id, [])) for expense in selected],
            "groups": groups,
            "errors": [asdict(error) for error in loaded.errors],
            "policy": {
                "name": policy["name"], "version": policy["version"],
                "categories": policy["categories"],
                "active_rules": [getattr(rule, "rule_name", type(rule).__name__) for rule in engine.rules],
            },
        }

    @application.get("/api/report")
    def report_data(
        employee: str | None = Query(default=None, max_length=200),
        search: str = Query(default="", max_length=200),
        dataset: str | None = Query(default=None, max_length=100),
    ):
        return serialize(sources.resolve(dataset), employee, search, dataset)

    @application.post("/api/report/upload")
    def upload_report(
        expenses: UploadFile | None = None,
        policy: UploadFile | None = None,
        dataset: str | None = Form(default=None, max_length=100),
    ):
        source = sources.prepare(expenses, policy, dataset)
        # Validate and run the complete pipeline before publishing a snapshot.
        data = serialize(source, None, "", None)
        data["dataset_id"] = sources.save(source)
        return data

    @application.get("/api/report/download", response_class=PlainTextResponse)
    def download_report(
        group_by: Literal["employee", "rule"] = "employee",
        employee: str | None = Query(default=None, max_length=200),
        search: str = Query(default="", max_length=200),
        dataset: str | None = Query(default=None, max_length=100),
    ):
        *_, report = _load(sources.resolve(dataset), employee, search)
        return PlainTextResponse(
            render_report(report, group_by=group_by),
            headers={"Content-Disposition": f'attachment; filename="expense-report-{group_by}.txt"'},
        )

    # One local server can serve the production build after `npm run build`.
    # During frontend development Vite proxies /api to this same API.
    dist = root / "frontend" / "dist"
    if dist.is_dir():
        application.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")
    return application


app = create_app()
