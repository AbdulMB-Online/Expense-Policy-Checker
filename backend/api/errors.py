"""Translate application/storage failures and keep private API data uncached."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from backend.database.errors import (
    AccessError,
    ReceiptNotFoundError,
    RecordNotFoundError,
    StorageError,
    SubmissionConflictError,
)
from backend.services.errors import ServiceError


def register_error_handlers(application: FastAPI) -> None:
    @application.middleware("http")
    async def private_api_responses(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(AccessError)
    async def access_error(_request, error):
        return JSONResponse(status_code=403, content={"detail": str(error)})

    @application.exception_handler(RecordNotFoundError)
    async def not_found(_request, error):
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @application.exception_handler(StorageError)
    @application.exception_handler(OSError)
    async def storage_error(_request, _error):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Submitted expenses could not be saved or loaded. Check local storage and retry."
            },
        )

    @application.exception_handler(SubmissionConflictError)
    async def submission_conflict(_request, error):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @application.exception_handler(ReceiptNotFoundError)
    async def receipt_not_found(_request, error):
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @application.exception_handler(ServiceError)
    async def service_error(_request, error):
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail})
