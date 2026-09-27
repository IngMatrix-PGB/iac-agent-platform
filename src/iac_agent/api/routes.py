"""Inbound HTTP routes. They call application services only."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from iac_agent.api.project import project_submission, project_view
from iac_agent.cli.ids import generate_request_id
from iac_agent.domain.workflow import validate_request_id
from iac_agent.intent.port import (
    IntentInterpreterError,
    IntentProviderRefusalError,
    IntentProviderTimeoutError,
    IntentProviderUnavailableError,
    IntentSchemaVersionUnsupportedError,
    IntentValidationError,
)

_INTERPRETER_ERRORS: dict[type[BaseException], tuple[str, str, int]] = {
    IntentProviderUnavailableError: (
        "intent_provider_unavailable",
        "Intent provider unavailable.",
        503,
    ),
    IntentProviderTimeoutError: (
        "intent_provider_timeout",
        "Intent provider timed out.",
        504,
    ),
    IntentProviderRefusalError: (
        "intent_provider_refusal",
        "Intent provider declined to produce structured output.",
        502,
    ),
    IntentValidationError: (
        "intent_payload_malformed",
        "Intent payload was malformed.",
        502,
    ),
    IntentSchemaVersionUnsupportedError: (
        "intent_schema_unsupported",
        "Intent schema version is unsupported.",
        502,
    ),
}


def register_routes(app: FastAPI) -> None:
    @app.post("/api/v1/requests")
    async def create_request(request: Request):
        payload, failure = await _read_json_object(request)
        if failure is not None:
            return failure
        assert payload is not None
        text = payload.get("natural_language_request")
        if not isinstance(text, str) or not text.strip():
            return _error("invalid_request", "Invalid request.", 400)
        request_id, id_error = _request_id(request, payload.get("request_id"))
        if id_error is not None:
            return id_error
        assert request_id is not None
        holder = request.app.state.holder
        if holder.application.read(request_id) is not None:
            return _error("request_exists", "Request already exists.", 409)
        try:
            result = holder.intent_service.submit(
                request_id=request_id, natural_language_request=text
            )
        except IntentInterpreterError as exc:
            code, message, status = _INTERPRETER_ERRORS.get(
                type(exc),
                ("intent_interpretation_failed", "Intent interpretation failed.", 502),
            )
            return _error(code, message, status, request_id=request_id)
        except Exception:
            return _error("internal_error", "Internal error.", 500)
        body = project_submission(result).model_dump()
        if result.workflow_view is None:
            return JSONResponse(body, status_code=200)
        return JSONResponse(
            body,
            status_code=201,
            headers={"Location": f"/api/v1/requests/{request_id}"},
        )

    @app.get("/api/v1/requests/{request_id}")
    def get_request(request_id: str, request: Request):
        try:
            validate_request_id(request_id)
        except ValueError:
            return _error("invalid_request_id", "Invalid request id.", 400)
        view = request.app.state.holder.application.read(request_id)
        if view is None:
            return _error("request_not_found", "Request not found.", 404)
        return project_view(view)


async def _read_json_object(request: Request) -> tuple[dict | None, JSONResponse | None]:
    try:
        payload = await request.json()
    except Exception:
        return None, _error("invalid_request", "Invalid request.", 400)
    if not isinstance(payload, dict):
        return None, _error("invalid_request", "Invalid request.", 400)
    return payload, None


def _request_id(request: Request, supplied: object) -> tuple[str | None, JSONResponse | None]:
    if supplied is None:
        state = request.app.state
        now = state.clock() if getattr(state, "clock", None) is not None else None
        entropy = getattr(state, "entropy", None)
        if entropy is None:
            return generate_request_id(now), None
        return generate_request_id(now, entropy=entropy), None
    if not isinstance(supplied, str):
        return None, _error("invalid_request_id", "Invalid request id.", 400)
    try:
        return validate_request_id(supplied), None
    except ValueError:
        return None, _error("invalid_request_id", "Invalid request id.", 400)


def _error(code: str, message: str, status: int, *, request_id: str | None = None) -> JSONResponse:
    body: dict[str, str] = {"error": code, "message": message}
    if request_id is not None:
        body["request_id"] = request_id
    return JSONResponse(body, status_code=status)
