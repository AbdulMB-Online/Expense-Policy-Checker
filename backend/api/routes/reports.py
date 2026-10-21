"""HTTP endpoints for reports."""

from typing import Literal

from fastapi import APIRouter, Depends, Form, Query, UploadFile
from fastapi.responses import PlainTextResponse

from backend.api.dependencies import Services, current_user, get_services, reviewer

router = APIRouter()


@router.get("/api/report")
def report_data(
    employee: str | None = Query(default=None, max_length=200),
    search: str = Query(default="", max_length=200),
    dataset: str | None = Query(default=None, max_length=100),
    user=Depends(current_user),
    services: Services = Depends(get_services),
):
    return services.reports.serialize(
        services.reports.resolve_source(dataset, user), employee, search, dataset, user
    )


@router.post("/api/report/upload")
def upload_report(
    expenses: UploadFile | None = None,
    policy: UploadFile | None = None,
    dataset: str | None = Form(default=None, max_length=100),
    user=Depends(reviewer),
    services: Services = Depends(get_services),
):
    return services.reports.upload(expenses, policy, dataset, user)


@router.get("/api/report/download", response_class=PlainTextResponse)
def download_report(
    group_by: Literal["employee", "rule"] = "employee",
    employee: str | None = Query(default=None, max_length=200),
    search: str = Query(default="", max_length=200),
    dataset: str | None = Query(default=None, max_length=100),
    user=Depends(current_user),
    services: Services = Depends(get_services),
):
    contents, artifact_id = services.reports.export(group_by, employee, search, dataset, user)
    return PlainTextResponse(
        contents,
        headers={
            "Content-Disposition": f'attachment; filename="expense-report-{group_by}.txt"',
            "X-Artifact-ID": artifact_id,
            "Cache-Control": "no-store",
        },
    )
