import tomllib
from pathlib import Path


def test_api_extra_owns_fastapi_and_uvicorn_without_httpx():
    data = tomllib.loads(Path("pyproject.toml").read_text())
    api = data["project"]["optional-dependencies"]["api"]
    dev = data["project"]["optional-dependencies"]["dev"]
    assert any(item.startswith("fastapi>=0.115,<1") for item in api)
    assert any(item.startswith("uvicorn>=0.32,<1") for item in api)
    assert not any(item.startswith("httpx") for item in api)
    assert any(item.startswith("httpx") for item in dev)
    assert any(item.startswith("fastapi") for item in dev)
    assert any(item.startswith("uvicorn") for item in dev)
