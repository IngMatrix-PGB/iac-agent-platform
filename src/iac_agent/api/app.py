"""ASGI factory. Tool adapters are constructed only by composition."""

from __future__ import annotations

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

    return app


def serve() -> None:
    import uvicorn

    uvicorn.run(create_app, factory=True, host=BIND_HOST, port=8000)
