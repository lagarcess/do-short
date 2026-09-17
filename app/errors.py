"""Structured JSON error responses + HTTP exception helpers."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """Domain error mapped to a structured JSON HTTP response."""

    def __init__(
        self,
        status_code: int,
        error: str,
        detail: str | None = None,
        code: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.error = error
        self.detail = detail
        self.code = code
        super().__init__(error)


def error_payload(error: str, detail: str | None = None, code: str | None = None) -> dict:
    body: dict = {"error": error}
    if detail is not None:
        body["detail"] = detail
    if code is not None:
        body["code"] = code
    return body


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(exc.error, exc.detail, exc.code),
    )


async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(detail, code="http_error"),
    )


async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_payload(
            "Validation failed",
            detail=str(exc.errors()),
            code="validation_error",
        ),
    )
