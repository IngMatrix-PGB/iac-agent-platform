"""Process entry for the dispatch-only live intent regression lane."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from evals.observability.layer2 import (
    DEFAULT_LAYER2_DIAGNOSTIC_PATH,
    build_layer2_document,
    write_layer2_diagnostic,
)
from evals.scenarios.architecture_intent_nl_loader import read_dataset_version
from evals.scenarios.architecture_intent_nl_runner import (
    DEFAULT_DATASET_PATH,
    run_architecture_intent_nl_evals,
)
from iac_agent.app.composition import create_intent_interpreter
from iac_agent.app.config import (
    MissingConfigurationError,
    load_intent_interpreter_config_from_env,
    load_openai_api_key_from_env,
)

_EXIT = {
    "PASS": 0,
    "SEMANTIC_REGRESSION": 1,
    "PROVIDER_ERROR": 2,
    "CONFIGURATION_ERROR": 3,
}


def main(env: Mapping[str, str] | None = None, diagnostic_path: Path | None = None) -> int:
    """Run one live regression and return the approved exit code."""
    selected = os.environ if env is None else env
    destination = Path(diagnostic_path or DEFAULT_LAYER2_DIAGNOSTIC_PATH)
    try:
        config = load_intent_interpreter_config_from_env(selected)
        api_key = load_openai_api_key_from_env(selected)
    except MissingConfigurationError:
        _write_configuration_error(destination, selected)
        return _EXIT["CONFIGURATION_ERROR"]
    interpreter = create_intent_interpreter(config, api_key=api_key)
    run_architecture_intent_nl_evals(
        interpreter=interpreter,
        diagnostic_path=destination,
        run_metadata=_run_metadata(
            selected,
            provider=config.provider.value,
            model=config.model,
        ),
    )
    payload = json.loads(destination.read_text(encoding="utf-8"))
    return _EXIT[str(payload["run"]["aggregate_result"])]


def _prompt_version() -> str:
    from iac_agent.intent.adapters.openai import _PROMPT_VERSION

    return _PROMPT_VERSION


def _run_id(env: Mapping[str, str]) -> str | None:
    run_id = env.get("GITHUB_RUN_ID", "").strip()
    attempt = env.get("GITHUB_RUN_ATTEMPT", "").strip()
    if run_id and attempt:
        return f"{run_id}-{attempt}"
    if run_id:
        return run_id
    return None


def _run_metadata(env: Mapping[str, str], *, provider: str, model: str) -> dict[str, str]:
    metadata = {
        "provider": provider,
        "model": model,
        "prompt_version": _prompt_version(),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if not metadata["provider"]:
        del metadata["provider"]
    if not metadata["model"]:
        del metadata["model"]
    git_sha = env.get("GITHUB_SHA", "").strip()
    if git_sha:
        metadata["git_sha"] = git_sha
    run_id = _run_id(env)
    if run_id is not None:
        metadata["run_id"] = run_id
    return metadata


def _write_configuration_error(path: Path, env: Mapping[str, str]) -> None:
    document = build_layer2_document(
        traces=(),
        dataset_path=str(DEFAULT_DATASET_PATH),
        run_metadata=_run_metadata(
            env,
            provider=env.get("IAC_AGENT_LLM_PROVIDER", ""),
            model=env.get("IAC_AGENT_LLM_MODEL", ""),
        ),
        interpreter_invocations=0,
        dataset_version=read_dataset_version(DEFAULT_DATASET_PATH),
        aggregate_override="CONFIGURATION_ERROR",
    )
    write_layer2_diagnostic(document, path=path)


if __name__ == "__main__":
    raise SystemExit(main())
