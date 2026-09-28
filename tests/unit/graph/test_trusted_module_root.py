from pathlib import Path

import pytest

from iac_agent.domain.resource import ResourceType
from iac_agent.graph.modules import trusted_module_dirs


def test_unset_root_points_at_checkout_modules(monkeypatch):
    monkeypatch.delenv("IAC_AGENT_TRUSTED_MODULE_ROOT", raising=False)
    from iac_agent.app.config import load_trusted_module_root

    dirs = trusted_module_dirs(load_trusted_module_root({}))
    assert dirs[ResourceType.SQS].is_dir()
    assert dirs[ResourceType.ECR].name == "ecr"


def test_configured_root_is_used_and_request_text_is_not_an_argument(tmp_path: Path):
    for name in ("sqs", "s3", "dynamodb", "lambda", "api_gateway", "ecr"):
        (tmp_path / "terraform" / "modules" / name).mkdir(parents=True)
    dirs = trusted_module_dirs(tmp_path)
    assert dirs[ResourceType.LAMBDA] == (tmp_path / "terraform" / "modules" / "lambda").resolve()


def test_relative_configured_root_is_rejected():
    from iac_agent.app.config import MissingConfigurationError, load_trusted_module_root

    with pytest.raises(MissingConfigurationError):
        load_trusted_module_root({"IAC_AGENT_TRUSTED_MODULE_ROOT": "terraform"})


def test_missing_module_directory_is_rejected(tmp_path: Path):
    (tmp_path / "terraform" / "modules" / "sqs").mkdir(parents=True)
    with pytest.raises(ValueError):
        trusted_module_dirs(tmp_path)
