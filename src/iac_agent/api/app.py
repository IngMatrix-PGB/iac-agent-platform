"""ASGI factory. Tool adapters are constructed only by composition."""

from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

BIND_HOST = "127.0.0.1"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    if app.state.holder is not None:
        yield
        return
    from iac_agent.app.composition import create_intent_interpreter, open_intent_application
    from iac_agent.app.config import (
        load_application_config_from_env,
        load_github_token_from_env,
        load_intent_interpreter_config_from_env,
        load_openai_api_key_from_env,
    )

    config = load_application_config_from_env()
    token = load_github_token_from_env()
    interpreter = create_intent_interpreter(
        load_intent_interpreter_config_from_env(),
        api_key=load_openai_api_key_from_env(),
    )
    with open_intent_application(config, github_token=token, interpreter=interpreter) as holder:
        app.state.holder = holder
        yield


def create_app(holder=None) -> FastAPI:
    app = FastAPI(title="iac-agent", lifespan=_lifespan)
    app.state.holder = holder

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready(request: Request):
        if request.app.state.holder is None:
            return JSONResponse({"status": "not_ready"}, status_code=503)
        return {"status": "ready"}

    from iac_agent.api.routes import register_routes

    register_routes(app)
    return app


def bind_host(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    host = source.get("IAC_AGENT_BIND_HOST", BIND_HOST).strip()
    if not host:
        raise ValueError("IAC_AGENT_BIND_HOST must not be blank")
    return host


def bind_port(env: Mapping[str, str] | None = None) -> int:
    source = os.environ if env is None else env
    raw = source.get("IAC_AGENT_PORT", "8000").strip()
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError(f"IAC_AGENT_PORT must be an integer, got {raw!r}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"IAC_AGENT_PORT must be from 1 to 65535, got {port}")
    return port


def serve() -> None:
    import uvicorn

    uvicorn.run(create_app, factory=True, host=bind_host(), port=bind_port())
