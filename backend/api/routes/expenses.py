"""HTTP endpoints for expenses."""

from fastapi import APIRouter, Depends, Form, Query, UploadFile

from backend.api.dependencies import Services, current_user, get_services, reviewer
from backend.api.responses import file_response
from backend.api.schemas import OwnerInput, ReviewInput

router = APIRouter()


@router.post("/api/receipts/extract")
def extract_receipt(
    receipt: UploadFile,
    dataset: str | None = Form(default=None, max_length=100),
    user=Depends(current_user),
    services: Services = Depends(get_services),
):
    source = services.reports.resolve_source(dataset, user)
    return services.receipts.extract(receipt, source.policy)


@router.post("/api/expenses", status_code=201)
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
    user=Depends(current_user),
    services: Services = Depends(get_services),
):
    return services.expenses.submit(
        {
            "employee": employee,
            "date": expense_date,
            "category": category,
            "amount": amount,
            "description": description,
            "nights": nights,
        },
        request_id,
        dataset,
        receipt,
        user,
    )


@router.post("/api/expenses/{expense_id}/review")
def review_expense(
    expense_id: str,
    body: ReviewInput,
    dataset: str | None = Query(default=None, max_length=100),
    user=Depends(reviewer),
    services: Services = Depends(get_services),
):
    return services.expenses.review(
        expense_id, body.run_id, body.revision_id, body.decision, body.comment, dataset, user
    )


@router.post("/api/expenses/{expense_id}/owner")
def map_expense(
    expense_id: str,
    body: OwnerInput,
    dataset: str | None = Query(default=None, max_length=100),
    user=Depends(reviewer),
    services: Services = Depends(get_services),
):
    return services.expenses.map_owner(expense_id, body.user_id, dataset, user)


@router.get("/api/expenses/{expense_id}/history")
def expense_history(
    expense_id: str,
    dataset: str | None = Query(default=None, max_length=100),
    user=Depends(current_user),
    services: Services = Depends(get_services),
):
    source = services.reports.resolve_source(dataset, user)
    return services.workspace.reviews.history(source.submission_scope, expense_id, user)


@router.put("/api/expenses/{expense_id}")
def resubmit_expense(
    expense_id: str,
    expense_date: str = Form(alias="date", max_length=10),
    category: str = Form(max_length=100),
    amount: str = Form(max_length=64),
    description: str = Form(max_length=2000),
    revision: int = Form(ge=1),
    nights: str = Form(default="", max_length=20),
    dataset: str | None = Form(default=None, max_length=100),
    receipt: UploadFile | None = None,
    user=Depends(current_user),
    services: Services = Depends(get_services),
):
    return services.expenses.resubmit(
        expense_id,
        {
            "date": expense_date,
            "category": category,
            "amount": amount,
            "description": description,
            "nights": nights,
        },
        revision,
        dataset,
        receipt,
        user,
    )


@router.get("/api/receipts/{expense_id}")
def download_receipt(
    expense_id: str,
    dataset: str | None = Query(default=None, max_length=100),
    user=Depends(current_user),
    services: Services = Depends(get_services),
):
    source = services.reports.resolve_source(dataset, user)
    services.workspace.reviews.expense(source.submission_scope, expense_id, user)
    receipt = services.submissions.receipt(source.submission_scope, expense_id)
    return file_response(receipt.name, receipt.media_type, receipt.contents)
