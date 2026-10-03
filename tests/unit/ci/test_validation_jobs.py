"""Classify itself is ungated; Quality, Tests, and Tool Validation stay ungated."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import yaml

_CI = Path(".github/workflows/ci.yml")
_ACTION = Path(".github/actions/real-tool-setup/action.yml")
_PRIVATE_CACHE_PATH = "${{ runner.temp }}/tf-plugin-cache"
_CACHE_KEY = (
    "tf-1.16.1-aws-6-${{ hashFiles('terraform/modules/**/versions.tf', "
    "'bootstrap/aws-oidc/versions.tf') }}"
)

_OUTPUT_NAMES = (
    "s3",
    "sqs",
    "dynamodb",
    "ecr",
    "lambda",
    "api_gateway",
    "api_lambda",
    "api_lambda_dynamodb",
    "serverless_worker",
    "security",
    "bootstrap",
    "frontend",
    "full",
    "reasons",
)

_CLASSIFY_COMMAND = re.compile(r"python scripts/ci_classify\.py\b")


def _jobs() -> dict:
    loaded = yaml.safe_load(_CI.read_text())
    return loaded["jobs"]


def _text() -> str:
    return _CI.read_text()


def _classify_script() -> str:
    classify = _jobs()["classify"]
    return "\n".join(step.get("run", "") for step in classify["steps"])


def _classify_invocations(script: str) -> list[str]:
    lines = script.splitlines()
    invocations: list[str] = []
    index = 0
    while index < len(lines):
        if not _CLASSIFY_COMMAND.search(lines[index]):
            index += 1
            continue
        parts = [lines[index]]
        while parts[-1].rstrip().endswith("\\") and index + 1 < len(lines):
            index += 1
            parts.append(lines[index])
        invocations.append(" ".join(part.replace("\\", " ") for part in parts))
        index += 1
    return invocations


def test_classify_itself_is_ungated_and_quality_tests_and_tool_validation_stay_ungated():
    jobs = _jobs()
    classify = jobs["classify"]
    assert classify["name"] == "Classify"
    assert classify["runs-on"] == "ubuntu-24.04"
    assert "if" not in classify
    assert "tool-validation" in jobs
    assert "if" not in jobs["tool-validation"]
    assert "if" not in jobs["quality"]
    assert "if" not in jobs["tests"]
    script = "\n".join(step.get("run", "") for step in classify["steps"])
    assert "scripts/ci_classify.py" in script
    assert "pytest -m real_tool" in _text()


def test_classify_outputs_include_reasons_and_every_shard():
    classify = _jobs()["classify"]
    outputs = classify["outputs"]
    assert list(outputs) == list(_OUTPUT_NAMES)
    for name in _OUTPUT_NAMES:
        assert outputs[name] == f"${{{{ steps.result.outputs.{name} }}}}"
    assert "needs" not in classify


def test_unreadable_invocation_passes_paths_file():
    invocations = _classify_invocations(_classify_script())
    unreadable = [invocation for invocation in invocations if "--unreadable" in invocation]
    assert unreadable
    for invocation in unreadable:
        assert "--paths-file" in invocation
        assert "--unreadable" in invocation


def test_unreadable_invocation_never_omits_paths_file():
    script = _classify_script()
    invocations = _classify_invocations(script)
    assert invocations
    assert not any(
        "--unreadable" in invocation and "--paths-file" not in invocation
        for invocation in invocations
    )
    assert "|| true" not in script


def test_workflow_has_no_paths_ignore():
    assert "paths-ignore" not in _text()


def test_classify_checkout_fetches_full_history():
    steps = _jobs()["classify"]["steps"]
    checkout = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["uses"] == "actions/checkout@v4"
    assert checkout["with"]["fetch-depth"] == 0


def test_quality_tests_and_tool_validation_have_no_if():
    jobs = _jobs()
    for key in ("quality", "tests", "tool-validation", "frontend"):
        assert "if" not in jobs[key]


def test_shard_conditions_only_read_classifier_outputs():
    jobs = _jobs()
    for key, output in (
        ("shard-s3", "s3"),
        ("shard-sqs", "sqs"),
        ("shard-dynamodb", "dynamodb"),
        ("shard-ecr", "ecr"),
        ("shard-lambda", "lambda"),
        ("shard-api-gateway", "api_gateway"),
        ("shard-api-lambda", "api_lambda"),
        ("shard-api-lambda-dynamodb", "api_lambda_dynamodb"),
        ("shard-serverless-worker", "serverless_worker"),
        ("shard-security", "security"),
    ):
        condition = jobs[key]["if"]
        assert condition == (
            "${{ !cancelled() && (needs.classify.result != 'success' || "
            f"needs.classify.outputs.{output} == 'true') }}}}"
        )
        assert "terraform/modules" not in condition
        assert jobs[key]["needs"] == "classify"
    assert "if" not in jobs["tool-validation"]
    tool_steps = jobs["tool-validation"]["steps"]
    action = next(
        step
        for step in tool_steps
        if str(step.get("uses", "")).startswith("./.github/actions/real-tool-setup")
    )
    assert action["with"]["pytest-args"] == "pytest -m real_tool"


_BOOTSTRAP_IF = (
    "${{ !cancelled() && (needs.classify.result != 'success' "
    "|| needs.classify.outputs.bootstrap == 'true') }}"
)

_ABSENT_VALIDATION_JOBS = ("aws-plan",)

_SHARD_JOBS = (
    ("shard-s3", "s3", "Terraform — S3"),
    ("shard-sqs", "sqs", "Terraform — SQS"),
    ("shard-dynamodb", "dynamodb", "Terraform — DynamoDB"),
    ("shard-ecr", "ecr", "Terraform — ECR"),
    ("shard-lambda", "lambda", "Terraform — Lambda"),
    ("shard-api-gateway", "api_gateway", "Terraform — API Gateway"),
    ("shard-api-lambda", "api_lambda", "Terraform — API Lambda"),
    ("shard-api-lambda-dynamodb", "api_lambda_dynamodb", "Terraform — API Lambda DynamoDB"),
    ("shard-serverless-worker", "serverless_worker", "Terraform — Serverless Worker"),
    ("shard-security", "security", "Security Validation"),
)

_FORBIDDEN_CREDENTIAL_TEXT = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "id-token",
    "aws-actions/configure-aws-credentials",
)


def test_bootstrap_validation_runs_credential_free_plan_when_classify_selects_or_fails():
    jobs = _jobs()
    job = jobs["bootstrap-validation"]
    assert job["name"] == "Bootstrap Validation"
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["needs"] == "classify"
    assert job["if"] == _BOOTSTRAP_IF
    assert "bootstrap/aws-oidc" not in job["if"]
    assert "path" not in job["if"].lower()
    script = "\n".join(step.get("run", "") for step in job["steps"])
    assert "pytest -m real_bootstrap_tool" in script
    assert "terraform apply" not in script
    assert "terraform destroy" not in script
    text = _text()
    for secret in _FORBIDDEN_CREDENTIAL_TEXT:
        assert secret not in text
    tool = jobs["tool-validation"]
    assert "if" not in tool
    tool_action = next(
        step
        for step in tool["steps"]
        if str(step.get("uses", "")).startswith("./.github/actions/real-tool-setup")
    )
    assert tool_action["with"]["pytest-args"] == "pytest -m real_tool"
    for key in _ABSENT_VALIDATION_JOBS:
        assert key not in jobs
    assert "if" not in jobs["frontend"]


def test_checkov_pin_is_a_requirements_file():
    pin = Path("ci/requirements-checkov.txt").read_text().strip()
    assert pin == "checkov==3.3.13"
    jobs = _jobs()
    tool = jobs["tool-validation"]
    assert "if" not in tool
    action = yaml.safe_load(_ACTION.read_text())
    setup = next(
        step
        for step in action["runs"]["steps"]
        if str(step.get("uses", "")).startswith("actions/setup-python@")
    )
    assert setup["uses"] == "actions/setup-python@v5"
    assert setup["with"]["python-version"] == "3.12"
    assert setup["with"]["cache"] == "pip"
    dependency_path = setup["with"]["cache-dependency-path"]
    assert "pyproject.toml" in dependency_path
    assert "ci/requirements-checkov.txt" in dependency_path
    script = "\n".join(step.get("run", "") for step in action["runs"]["steps"])
    assert 'pip install -e ".[dev]"' in script
    assert "pip install -r ci/requirements-checkov.txt" in script
    assert "pip install checkov==" not in script
    tool_action = next(
        step
        for step in tool["steps"]
        if str(step.get("uses", "")).startswith("./.github/actions/real-tool-setup")
    )
    assert tool_action["with"]["pytest-args"] == "pytest -m real_tool"
    bootstrap = jobs["bootstrap-validation"]
    bootstrap_script = "\n".join(step.get("run", "") for step in bootstrap["steps"])
    assert "checkov" not in bootstrap_script
    assert "ci/requirements-checkov.txt" not in bootstrap_script
    assert "pytest -m real_bootstrap_tool" in bootstrap_script
    assert bootstrap["if"] == _BOOTSTRAP_IF
    for key in _ABSENT_VALIDATION_JOBS:
        assert key not in jobs


def test_real_tool_setup_restores_and_does_not_save():
    action = Path(".github/actions/real-tool-setup/action.yml").read_text()
    assert "actions/cache/restore@v4" in action
    assert "actions/cache/save@" not in action
    assert "hashicorp/setup-terraform@v3" in action
    assert 'terraform_version: "1.16.1"' in action
    assert "pip install -r ci/requirements-checkov.txt" in action
    assert "AWS_ACCESS_KEY_ID" not in action
    assert "terraform apply" not in action


def test_provider_cache_saves_only_on_main_push():
    job = _jobs()["provider-cache"]
    assert job["name"] == "Provider Cache"
    assert job["if"] == "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    assert "actions/cache/save@v4" in _text()
    script = "\n".join(step.get("run", "") for step in job["steps"])
    assert "terraform init -backend=false" in script
    assert "terraform apply" not in script


def _uses(step: dict) -> str:
    return str(step.get("uses", ""))


def test_private_provider_cache_uses_one_path_and_saves_only_on_a_main_miss():
    action_text = _ACTION.read_text()
    action = yaml.safe_load(action_text)
    action_steps = action["runs"]["steps"]
    action_restores = [
        step for step in action_steps if _uses(step).startswith("actions/cache/restore@")
    ]
    assert [step["uses"] for step in action_restores] == ["actions/cache/restore@v4"]
    assert all(not _uses(step).startswith("actions/cache/save@") for step in action_steps)
    action_restore = action_restores[0]
    assert action_restore["with"]["path"] == _PRIVATE_CACHE_PATH
    assert action_restore["with"]["key"] == _CACHE_KEY
    assert "restore-keys" not in action_restore["with"]
    assert "restore-keys" not in action_text
    assert "provider-restore" not in action_text
    action_script = "\n".join(step.get("run", "") for step in action_steps)
    assert 'mkdir -p "${{ runner.temp }}/tf-plugin-cache"' in action_script
    assert (
        'echo "TF_PLUGIN_CACHE_DIR=${{ runner.temp }}/tf-plugin-cache" >> "$GITHUB_ENV"'
        in action_script
    )
    assert "AWS_EC2_METADATA_DISABLED" in action_text
    assert "${{ inputs.pytest-args }}" in action_script
    assert "id-token" not in action_text
    assert "terraform destroy" not in action_text

    workflow = _text()
    assert "restore-keys" not in workflow
    assert "provider-restore" not in workflow
    jobs = _jobs()
    for key in _ABSENT_VALIDATION_JOBS:
        assert key not in jobs

    tool = jobs["tool-validation"]
    assert "if" not in tool
    assert tool["runs-on"] == "ubuntu-24.04"
    tool_uses = [_uses(step) for step in tool["steps"]]
    assert "actions/checkout@v4" in tool_uses
    assert any(item.startswith("./.github/actions/real-tool-setup") for item in tool_uses)
    assert not any(item.startswith("actions/cache/") for item in tool_uses)
    assert not any(item.startswith("actions/setup-python@") for item in tool_uses)
    tool_action = next(
        step
        for step in tool["steps"]
        if _uses(step).startswith("./.github/actions/real-tool-setup")
    )
    assert tool_action["with"]["pytest-args"] == "pytest -m real_tool"

    job = jobs["provider-cache"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["name"] == "Provider Cache"
    assert job["if"] == "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    restores = [step for step in job["steps"] if _uses(step).startswith("actions/cache/restore@")]
    saves = [step for step in job["steps"] if _uses(step).startswith("actions/cache/save@")]
    assert [step["uses"] for step in restores] == ["actions/cache/restore@v4"]
    assert [step["uses"] for step in saves] == ["actions/cache/save@v4"]
    restore = restores[0]
    save = saves[0]
    assert restore["with"]["path"] == _PRIVATE_CACHE_PATH
    assert save["with"]["path"] == _PRIVATE_CACHE_PATH
    assert restore["with"]["path"] == save["with"]["path"] == action_restore["with"]["path"]
    assert restore["with"]["key"] == _CACHE_KEY
    assert save["with"]["key"] == _CACHE_KEY
    assert restore["with"]["key"] == save["with"]["key"] == action_restore["with"]["key"]
    assert "restore-keys" not in restore["with"]
    assert "restore-keys" not in save["with"]
    assert save["if"] == "success() && steps.restore.outputs.cache-hit != 'true'"
    assert restore.get("id") == "restore"
    for name, other in jobs.items():
        for step in other["steps"]:
            if _uses(step).startswith("actions/cache/save@"):
                assert name == "provider-cache"
                assert step["uses"] == "actions/cache/save@v4"
    script = "\n".join(step.get("run", "") for step in job["steps"])
    assert 'mkdir -p "$RUNNER_TEMP/tf-plugin-cache"' in script
    assert "cp -R terraform/modules/s3" in script
    assert "$RUNNER_TEMP/s3-init" in script
    assert "export TF_PLUGIN_CACHE_DIR=$RUNNER_TEMP/tf-plugin-cache" in script
    assert "export AWS_EC2_METADATA_DISABLED=true" in script
    assert 'cd "$RUNNER_TEMP/s3-init"' in script
    assert "terraform init -backend=false" in script
    assert "terraform apply" not in script
    assert "terraform destroy" not in script
    assert save["with"]["path"] == "${{ runner.temp }}/tf-plugin-cache"

    bootstrap = jobs["bootstrap-validation"]
    assert bootstrap["name"] == "Bootstrap Validation"
    assert bootstrap["needs"] == "classify"
    assert bootstrap["if"] == _BOOTSTRAP_IF
    assert bootstrap["runs-on"] == "ubuntu-24.04"
    bootstrap_uses = [step["uses"] for step in bootstrap["steps"] if "uses" in step]
    assert bootstrap_uses == [
        "actions/checkout@v4",
        "actions/setup-python@v5",
        "hashicorp/setup-terraform@v3",
    ]
    bootstrap_script = "\n".join(step.get("run", "") for step in bootstrap["steps"])
    assert "pytest -m real_bootstrap_tool" in bootstrap_script
    assert "checkov" not in bootstrap_script
    assert "TF_PLUGIN_CACHE_DIR" not in bootstrap_script
    assert "tf-plugin-cache" not in bootstrap_script
    assert "actions/cache" not in bootstrap_script


def _fail_closed(output: str) -> str:
    return (
        "${{ !cancelled() && (needs.classify.result != 'success' || "
        f"needs.classify.outputs.{output} == 'true') }}}}"
    )


def _load_shard_files() -> dict[str, tuple[str, ...]]:
    path = Path(__file__).resolve().parents[3] / "scripts" / "ci_classify.py"
    spec = importlib.util.spec_from_file_location("ci_classify", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"classifier module is missing: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SHARD_FILES


def _real_tool_setup(job: dict) -> dict:
    return next(
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("./.github/actions/real-tool-setup")
    )


def _listed_files(pytest_args: str) -> tuple[str, ...]:
    prefix = "pytest -m real_tool "
    assert pytest_args.startswith(prefix)
    parts = pytest_args.removeprefix(prefix).split()
    assert parts
    assert all(part.startswith("tests/integration/") for part in parts)
    return tuple(Path(part).name for part in parts)


def test_shard_jobs_lock_names_needs_and_fail_closed_conditions():
    jobs = _jobs()
    shard_keys = {key for key, _, _ in _SHARD_JOBS}
    assert shard_keys == {name for name in jobs if name.startswith("shard-")}
    for key, output, display_name in _SHARD_JOBS:
        job = jobs[key]
        condition = job["if"]
        assert job["name"] == display_name
        assert job["runs-on"] == "ubuntu-24.04"
        assert job["needs"] == "classify"
        assert condition == _fail_closed(output)
        assert "terraform/modules" not in condition
        assert "serverless_worker/" not in condition
        assert [step.get("uses") for step in job["steps"]] == [
            "actions/checkout@v4",
            "./.github/actions/real-tool-setup",
        ]
        for step in job["steps"]:
            assert not str(step.get("uses", "")).startswith("actions/cache/save")
    assert "if" not in jobs["tool-validation"]
    assert _real_tool_setup(jobs["tool-validation"])["with"]["pytest-args"] == "pytest -m real_tool"
    assert "aws-plan" not in jobs


def test_shard_pytest_args_follow_shard_files_without_overlap():
    jobs = _jobs()
    shard_files = _load_shard_files()
    assert set(shard_files) == {output for _, output, _ in _SHARD_JOBS}
    listed: dict[str, tuple[str, ...]] = {}
    for key, output, _display_name in _SHARD_JOBS:
        expected = "pytest -m real_tool " + " ".join(
            f"tests/integration/{name}" for name in shard_files[output]
        )
        pytest_args = _real_tool_setup(jobs[key])["with"]["pytest-args"]
        assert pytest_args == expected
        listed[key] = _listed_files(pytest_args)
        assert listed[key] == tuple(shard_files[output])
    workflow_union = {name for files in listed.values() for name in files}
    classifier_union = {name for files in shard_files.values() for name in files}
    assert workflow_union == classifier_union
    keys = list(listed)
    for index, left in enumerate(keys):
        for right in keys[index + 1 :]:
            assert set(listed[left]).isdisjoint(set(listed[right]))
    assert "test_sqs_renderer_terraform.py" not in listed["shard-s3"]
    assert "test_lambda_renderer_terraform.py" not in listed["shard-sqs"]
