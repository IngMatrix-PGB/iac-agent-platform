"""HTTP-edge check for the single operator secret. No persistence."""

from __future__ import annotations

import hmac

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import SecretStr

_UNAUTHORIZED_BODY = {"error": "unauthenticated", "message": "Authentication is required."}


def authenticate_operator(request: Request) -> JSONResponse | None:
    """Return a 401 response, or None when the bearer matches the configured secret.

    Missing, malformed, and wrong credentials share one body. This function
    does not read the path, the query string, or the application holder.
    """
    secret = getattr(request.app.state, "operator_secret", None)
    if not isinstance(secret, SecretStr):
        return _unauthorized()
    header = request.headers.get("authorization", "")
    scheme, separator, token = header.partition(" ")
    if scheme != "Bearer" or separator != " " or token == "" or " " in token:
        return _unauthorized()
    expected = secret.get_secret_value().encode("utf-8")
    supplied = token.encode("utf-8")
    if not hmac.compare_digest(expected, supplied):
        return _unauthorized()
    return None


def _unauthorized() -> JSONResponse:
    return JSONResponse(_UNAUTHORIZED_BODY, status_code=401)
