"""HTTP endpoints for sessions."""

from fastapi import APIRouter, Cookie, Depends
from fastapi.responses import JSONResponse, Response

from backend.api.dependencies import Services, current_user, get_services
from backend.api.schemas import LoginInput

router = APIRouter()


@router.get("/api/health")
def health():
    return {"status": "ok"}


@router.get("/api/demo/accounts")
def accounts(
    services: Services = Depends(get_services),
):
    return services.workspace.sessions.users()


@router.post("/api/demo/login")
def login(
    body: LoginInput,
    expense_session: str | None = Cookie(default=None),
    services: Services = Depends(get_services),
):
    token, user = services.workspace.sessions.login(body.user_id)
    services.workspace.sessions.logout(expense_session)
    response = JSONResponse(user)
    response.set_cookie("expense_session", token, httponly=True, samesite="strict", max_age=86400)
    return response


@router.get("/api/session")
def session(user=Depends(current_user)):
    return user


@router.post("/api/demo/logout", status_code=204)
def logout(
    expense_session: str | None = Cookie(default=None),
    services: Services = Depends(get_services),
):
    services.workspace.sessions.logout(expense_session)
    response = Response(status_code=204)
    response.delete_cookie("expense_session")
    return response
