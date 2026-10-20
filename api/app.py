"""Expose the existing expense pipeline to React without duplicating rules."""

import csv
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import DecimalException
from pathlib import Path
from secrets import token_urlsafe
import sqlite3
from typing import Literal
from urllib.parse import quote, urlencode

from fastapi import FastAPI, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from api.sources import ReportSource, SourceStore
from api.submissions import SubmissionStore, parse_expense, read_receipt, validate_request_id
from loader.expense_loader import Expense, LoadResult
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


def _claim(expense: Expense, violations: list | tuple, saved: dict, dataset: str | None) -> dict:
    submission = saved.get(expense.id)
    receipt_url = f"/api/receipts/{expense.id}" + ("?" + urlencode({"dataset": dataset}) if dataset else "")
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
        "receipt": {"name": submission.receipt_name, "download_url": receipt_url} if submission and submission.receipt_name else None,
        "status": "flagged" if violations else "unflagged",
        "violations": [asdict(violation) for violation in violations],
    }


def _with_submissions(source: ReportSource, expenses: tuple[Expense, ...]) -> ReportSource:
    if {expense.id for expense in source.loaded.expenses} & {expense.id for expense in expenses}:
        raise HTTPException(409, "Expense IDs in this CSV conflict with submitted claims. Use unique expense IDs.")
    return replace(source, loaded=LoadResult(source.loaded.expenses + expenses, source.loaded.errors))


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
    submissions = SubmissionStore(root)

    @application.exception_handler(sqlite3.Error)
    @application.exception_handler(OSError)
    async def storage_error(_request, _error):
        return JSONResponse(status_code=503, content={"detail": "Submitted expenses could not be saved or loaded. Check local storage and retry."})

    @application.get("/api/health")
    def health():
        return {"status": "ok"}

    def serialize(source: ReportSource, employee: str | None, search: str, dataset: str | None):
        saved = {item.expense.id: item for item in submissions.list(source.submission_scope)}
        source = _with_submissions(source, tuple(item.expense for item in saved.values()))
        loaded, policy, employees, violations, selected, engine, all_report, report = _load(source, employee, search)
        def claim(expense, reasons):
            return _claim(expense, reasons, saved, dataset)
        groups = {}
        for grouping in ("employee", "rule"):
            groups[grouping] = [
                {
                    "id": group.key,
                    "name": group.name,
                    "total_amount": f"{group.total_flagged_amount:.2f}",
                    "claims": [claim(item.expense, item.violations) for item in group.expenses],
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
            "claims": [claim(expense, violations.get(expense.id, [])) for expense in selected],
            "submissions": [claim(item.expense, violations.get(item.expense.id, [])) for item in saved.values()],
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
        token = token_urlsafe(24)
        data = serialize(source, None, "", token)
        sources.save(source, token)
        return data

    @application.post("/api/expenses", status_code=201)
    def submit_expense(
        employee: str = Form(max_length=200),
        expense_date: str = Form(alias="date", max_length=10),
        category: str = Form(max_length=100),
        amount: str = Form(max_length=64),
        description: str = Form(max_length=2000),
        request_id: str = Form(max_length=100),
        nights: str = Form(default="", max_length=20),
        dataset: str | None = Form(default=None, max_length=100),
        receipt: UploadFile | None = None,
    ):
        source = sources.resolve(dataset)
        key = validate_request_id(request_id)
        attachment = read_receipt(receipt)
        expense = parse_expense({
            "employee": employee, "date": expense_date, "category": category,
            "amount": amount, "description": description, "nights": nights,
        }, source.policy, attachment is not None)
        claim_id = submissions.save(source.submission_scope, key, expense, attachment,
            lambda records: _load(_with_submissions(source, records), None, ""))
        data = serialize(source, None, "", dataset)
        return {"claim": next(claim for claim in data["submissions"] if claim["id"] == claim_id), "report": data}

    @application.get("/api/receipts/{expense_id}")
    def download_receipt(expense_id: str, dataset: str | None = Query(default=None, max_length=100)):
        source = sources.resolve(dataset)
        receipt = submissions.receipt(source.submission_scope, expense_id)
        return Response(receipt.contents, media_type=receipt.media_type, headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(receipt.name, safe=""),
            "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
        })

    @application.get("/api/report/download", response_class=PlainTextResponse)
    def download_report(
        group_by: Literal["employee", "rule"] = "employee",
        employee: str | None = Query(default=None, max_length=200),
        search: str = Query(default="", max_length=200),
        dataset: str | None = Query(default=None, max_length=100),
    ):
        source = sources.resolve(dataset)
        saved = submissions.list(source.submission_scope)
        *_, report = _load(_with_submissions(source, tuple(item.expense for item in saved)), employee, search)
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
