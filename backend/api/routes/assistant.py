"""Reviewer-only report conversation using the shared report service."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.api.dependencies import Services, get_services, reviewer
from backend.assistant.service import AssistantError, ChatRequest

router = APIRouter()


@router.get("/api/assistant/status")
def assistant_status(request: Request, user=Depends(reviewer)):
    return JSONResponse(request.app.state.assistant.status(), headers={"Cache-Control": "no-store"})


@router.post("/api/assistant/chat")
def assistant_chat(
    body: ChatRequest,
    request: Request,
    user=Depends(reviewer),
    services: Services = Depends(get_services),
):
    source = services.reports.resolve_source(body.dataset, user)
    data = services.reports.serialize(source, body.employee, body.search, body.dataset, user)
    try:
        answer = request.app.state.assistant.answer(data, source.policy, body)
        return JSONResponse(answer, headers={"Cache-Control": "no-store"})
    except AssistantError as error:
        raise HTTPException(error.status, str(error)) from error
