# CI Validation Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split credential-free real-tool CI by blast radius, add Bootstrap Validation, and remove the monolithic Tool Validation job only after the shard union is shown to match today's suite.

**Architecture:** `scripts/ci_classify.py` is the only place that maps a changed path to shards. Workflow jobs read its boolean outputs. They do not restate module edges. Tool Validation keeps running `pytest -m real_tool` until a later commit, on a revision that already passed both the monolith and every shard.

**Tech Stack:** GitHub Actions on `ubuntu-24.04`, Python 3.12, pytest, Terraform 1.16.1, Checkov 3.3.13, `hashicorp/aws` `~> 6.0`, existing actions `actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4`, `hashicorp/setup-terraform@v3`.

## Global Constraints

- Baseline is `main` at `2f611ef` on branch `docs/b37-ci-validation-architecture`. Do not merge, cherry-pick, or recreate the `aws-plan` job from PR #22.
- Do not edit AWS IAM, OIDC trust, `bootstrap/aws-oidc/*.tf`, or `IaCPlanRole`.
- Do not add `terraform apply` or `terraform destroy`.
- Do not put `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, or `id-token` in workflow YAML.
- Do not change branch protection or required checks. Required contexts stay `Quality` and `Tests`.
- Do not change the major version of an action already pinned in `.github/workflows/ci.yml`. `actions/cache/restore@v4` and `actions/cache/save@v4` are new uses at the same major generation as `actions/checkout@v4`, not upgrades of existing steps.
- `Quality` and `Tests` have no `if` and no `paths-ignore`.
- The dependency graph lives in `scripts/ci_classify.py`. A shard job `if` may only read `needs.classify.result` and `needs.classify.outputs.<name>`.
- Bootstrap Validation runs the existing `real_bootstrap_tool` tests in `tests/integration/test_bootstrap_aws_oidc_terraform.py`. On this baseline those tests `fmt` the module and `plan` a temp copy with a test-owned skip-flag override. They expect creates for `aws_iam_openid_connect_provider`, `aws_iam_role`, and `aws_iam_role_policy`. Do not rewrite them into the unmerged data-source `terraform test`.
- `TerraformRunner` allowlist stays `PATH` and `HOME`. Do not widen it so a workflow env var can leak into product plans.
- Placeholder AWS keys stay inside existing tests. Do not add them to YAML.
- Commit messages pass `scripts/check_commit_attribution.py`. No `Co-Authored-By`, `Generated-By`, or `Made with Cursor` / `Made with Claude`. Do not change git config. If the local commit wrapper appends a trailer, build the commit with `git commit-tree` and `git reset --soft` using the existing author name and email. Do not use `--no-verify`.
- One phase, then stop. Do not start the next phase in the same session.

---

## File map

| File | Responsibility |
| --- | --- |
| `scripts/ci_classify.py` | Ownership table, path rules, `classify`, CLI, GitHub output |
| `tests/unit/ci/test_validation_classifier.py` | Ownership, transitivity, fail-closed, CLI |
| `tests/unit/ci/test_runner_image.py` | `ubuntu-24.04` and unchanged action majors |
| `tests/unit/ci/test_validation_jobs.py` | Job names, `if` expressions, no apply/destroy, no aws-plan |
| `tests/unit/test_tf_plugin_cache_dir.py` | CI-provided plugin cache is reused |
| `tests/integration/conftest.py` | Honor `TF_PLUGIN_CACHE_DIR` when set |
| `ci/requirements-checkov.txt` | `checkov==3.3.13` |
| `.github/actions/real-tool-setup/action.yml` | Install toolchain and restore a private plugin cache |
| `.github/workflows/ci.yml` | Image pin, Classify, Bootstrap Validation, shards, cache save |
| `docs/ci.md` | Job list matching the phase that is actually on the branch |

`tests/unit/ci/test_aws_plan_workflow_structure.py` stays as it is. Its xfail contract is that `aws-plan` does not exist.

---

### Task 1: Pin ubuntu-24.04

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `tests/unit/ci/test_runner_image.py`
- Modify: `docs/ci.md`

**Interfaces:**
- Consumes: current jobs `quality`, `tests`, `tool-validation`, `frontend`
- Produces: every job `runs-on: ubuntu-24.04`. Action refs stay `@v4`, `@v5`, `@v4`, `@v3` for checkout, setup-python, setup-node, setup-terraform.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

import yaml

_CI = Path(".github/workflows/ci.yml")


def _jobs() -> dict:
    return yaml.safe_load(_CI.read_text())["jobs"]


def test_every_job_runs_on_ubuntu_24_04():
    for name, job in _jobs().items():
        assert job["runs-on"] == "ubuntu-24.04", name


def test_existing_action_majors_stay_put():
    text = _CI.read_text()
    assert "actions/checkout@v4" in text
    assert "actions/setup-python@v5" in text
    assert "actions/setup-node@v4" in text
    assert "hashicorp/setup-terraform@v3" in text
    assert "actions/checkout@v7" not in text
    assert "actions/setup-python@v6" not in text
    assert "hashicorp/setup-terraform@v4" not in text
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `pytest tests/unit/ci/test_runner_image.py -v`

Expected: FAIL because jobs still say `ubuntu-latest`.

- [ ] **Step 3: Pin the image and document it**

In `.github/workflows/ci.yml`, replace all four `runs-on: ubuntu-latest` lines with `runs-on: ubuntu-24.04`. Leave every `uses:` ref unchanged. Leave the Tool Validation steps unchanged, including `pytest -m real_tool`.

In `docs/ci.md`, under the opening paragraph, add: "Every job runs on `ubuntu-24.04`."

- [ ] **Step 4: Run the test and the workflow structure tests**

Run: `pytest tests/unit/ci/test_runner_image.py tests/unit/ci/test_frontend_job.py tests/unit/ci/test_aws_plan_workflow_structure.py -v`

Expected: PASS. The aws-plan existence tests remain xfail. `test_id_token_write_is_scoped_only_to_the_aws_plan_job` passes because no job gained `id-token`.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml tests/unit/ci/test_runner_image.py docs/ci.md
git commit -m "$(cat <<'EOF'
ci: pin GitHub runners to ubuntu-24.04

The measured image was already Ubuntu 24.04. Pin it before any later
job split, without changing action majors or Tool Validation.
EOF
)"
```

### Checkpoint A

Stop. Do not start Task 2 in the same session.

Confirm `git diff HEAD~1 -- .github/workflows/ci.yml` shows only `runs-on` and that `pytest -m real_tool` is still the Tool Validation command. The next session starts at Task 2 only after this commit exists.

---

### Task 2: Shard ownership map

**Files:**
- Create: `scripts/ci_classify.py`
- Create: `tests/unit/ci/test_validation_classifier.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `SHARD_ORDER: tuple[str, ...]`
  - `SHARD_FILES: dict[str, tuple[str, ...]]`
  - `SHARD_CONSUMES: dict[str, frozenset[str]]`
  - `classify(paths: list[str] | None, *, failed: bool = False) -> Selection`
  - `Selection` fields: `shards: frozenset[str]`, `bootstrap: bool`, `frontend: bool`, `full: bool`, `reasons: tuple[str, ...]`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/ci/test_validation_classifier.py` with the cases below. Load the script with `importlib` because `scripts/` is not a package:

```python
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_PATH = Path("scripts/ci_classify.py")


def _load():
    spec = importlib.util.spec_from_file_location("ci_classify", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_real_tool_file_has_one_owner():
    module = _load()
    owned = [name for files in module.SHARD_FILES.values() for name in files]
    assert len(owned) == len(set(owned))
    collected = _real_tool_files()
    assert set(owned) == collected


def test_union_has_no_omissions():
    module = _load()
    owned = {name for files in module.SHARD_FILES.values() for name in files}
    assert owned == _real_tool_files()
    assert len(module.SHARD_FILES) == 10


def _real_tool_files() -> set[str]:
    found = set()
    for path in Path("tests/integration").glob("test_*.py"):
        if "pytest.mark.real_tool" in path.read_text():
            found.add(path.name)
    return found
```

```python
@pytest.mark.parametrize(
    ("path", "shards", "bootstrap", "frontend"),
    [
        ("terraform/modules/sqs/main.tf", {"sqs", "serverless_worker", "security"}, False, False),
        ("src/iac_agent/providers/aws/sqs/renderer.py", {"sqs", "serverless_worker", "security"}, False, False),
        ("terraform/modules/lambda/main.tf", {"lambda", "api_lambda", "api_lambda_dynamodb", "serverless_worker"}, False, False),
        ("terraform/modules/dynamodb/main.tf", {"dynamodb", "api_lambda_dynamodb", "serverless_worker"}, False, False),
        ("terraform/modules/api_gateway/main.tf", {"api_gateway", "api_lambda", "api_lambda_dynamodb"}, False, False),
        ("terraform/modules/s3/main.tf", {"s3"}, False, False),
        ("terraform/modules/ecr/main.tf", {"ecr"}, False, False),
        ("src/iac_agent/providers/aws/kms.py", {"s3", "sqs", "serverless_worker", "security"}, False, False),
        ("src/iac_agent/compositions/serverless_worker/renderer.py", {"serverless_worker"}, False, False),
        ("src/iac_agent/compositions/api_lambda/renderer.py", {"api_lambda"}, False, False),
        ("src/iac_agent/compositions/api_lambda_dynamodb/renderer.py", {"api_lambda_dynamodb"}, False, False),
        ("tests/integration/test_s3_renderer_terraform.py", {"s3"}, False, False),
        ("docs/ci.md", set(), False, False),
        ("README.md", set(), False, False),
        ("ui/src/App.tsx", set(), False, True),
        ("bootstrap/aws-oidc/main.tf", set(), True, False),
    ],
)
def test_path_selection(path, shards, bootstrap, frontend):
    result = _load().classify([path])
    assert result.shards == frozenset(shards)
    assert result.bootstrap is bootstrap
    assert result.frontend is frontend


def test_sqs_does_not_select_unrelated_families():
    shards = _load().classify(["terraform/modules/sqs/main.tf"]).shards
    assert shards.isdisjoint({"s3", "ecr", "lambda"})


def test_lambda_does_not_select_s3_or_ecr():
    shards = _load().classify(["terraform/modules/lambda/main.tf"]).shards
    assert shards.isdisjoint({"s3", "ecr"})


def test_dynamodb_does_not_select_s3_or_sqs():
    shards = _load().classify(["terraform/modules/dynamodb/main.tf"]).shards
    assert shards.isdisjoint({"s3", "sqs"})


def test_kms_does_not_select_lambda_dynamodb_or_ecr():
    shards = _load().classify(["src/iac_agent/providers/aws/kms.py"]).shards
    assert shards.isdisjoint({"lambda", "dynamodb", "ecr", "api_gateway"})


@pytest.mark.parametrize(
    "path",
    [
        "src/iac_agent/graph/workflow.py",
        "src/iac_agent/execution/terraform_runner.py",
        "src/iac_agent/security/checkov_profiles.py",
        "src/iac_agent/policies/platform.py",
        "src/iac_agent/app/composition.py",
        "src/iac_agent/providers/aws/renderer.py",
        "src/iac_agent/providers/aws/resource.py",
        "src/iac_agent/providers/aws/terraform_render.py",
        "src/iac_agent/providers/aws/__init__.py",
        "terraform/modules/newfam/main.tf",
        "src/iac_agent/intent/models.py",
    ],
)
def test_shared_or_unknown_path_selects_every_shard_without_bootstrap_or_frontend(path):
    module = _load()
    result = module.classify([path])
    assert result.shards == frozenset(module.SHARD_ORDER)
    assert result.full is True
    assert result.bootstrap is False
    assert result.frontend is False


def test_workflow_path_selects_full_validation_plus_bootstrap_and_frontend():
    module = _load()
    result = module.classify([".github/workflows/ci.yml"])
    assert result.shards == frozenset(module.SHARD_ORDER)
    assert result.full is True
    assert result.bootstrap is True
    assert result.frontend is True


def test_collected_real_tool_nodes_match_shard_files():
    module = _load()
    owned = [name for files in module.SHARD_FILES.values() for name in files]
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", "real_tool"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    files = set()
    for line in completed.stdout.splitlines():
        if "::" not in line or line.startswith("tests/integration/") is False:
            continue
        files.add(Path(line.split("::", 1)[0]).name)
    assert files == set(owned)
```

The collection test is part of the deterministic suite. It does not execute the real-tool bodies.

Fail-closed tests:

```python
def test_empty_diff_selects_full_failure_set():
    result = _load().classify([])
    assert result.full is True
    assert result.shards == frozenset(_load().SHARD_ORDER)
    assert result.bootstrap is True
    assert result.frontend is True


def test_unreadable_diff_selects_full_failure_set():
    result = _load().classify(None)
    assert result.bootstrap is True
    assert result.frontend is True
    assert result.full is True


def test_classifier_failure_flag_selects_full_failure_set():
    result = _load().classify(["docs/ci.md"], failed=True)
    assert result.full is True
    assert result.bootstrap is True
    assert result.frontend is True


def test_docs_plus_s3_is_only_s3():
    result = _load().classify(["docs/ci.md", "terraform/modules/s3/main.tf"])
    assert result.shards == frozenset({"s3"})
    assert result.frontend is False
    assert result.bootstrap is False


def test_ui_plus_s3_unions_frontend():
    result = _load().classify(["ui/src/App.tsx", "terraform/modules/s3/main.tf"])
    assert result.shards == frozenset({"s3"})
    assert result.frontend is True


def test_docs_only_selects_nothing_extra():
    result = _load().classify(["docs/ci.md", "README.md"])
    assert result.shards == frozenset()
    assert result.full is False
    assert result.frontend is False
    assert result.bootstrap is False
```

KMS importer test, in the same file:

```python
def test_kms_importers_are_s3_and_sqs_contracts():
    root = Path("src")
    importers = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if "from iac_agent.providers.aws.kms import validate_kms_key_id" in path.read_text()
    )
    assert importers == [
        "iac_agent/providers/aws/s3/contract.py",
        "iac_agent/providers/aws/sqs/contract.py",
    ]
```

Module directory test:

```python
def test_every_terraform_module_directory_has_a_prefix_row():
    module = _load()
    names = sorted(path.name for path in Path("terraform/modules").iterdir() if path.is_dir())
    assert names == ["api_gateway", "dynamodb", "ecr", "lambda", "s3", "sqs"]
    for name in names:
        result = module.classify([f"terraform/modules/{name}/main.tf"])
        assert any(name in module.SHARD_CONSUMES[shard] for shard in result.shards)
```

The last assertion is the consumer closure: the owning module name appears in `SHARD_CONSUMES` of at least one selected shard. For `s3`, the selected shard's consume set contains `s3`.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `pytest tests/unit/ci/test_validation_classifier.py -v`

Expected: FAIL with `FileNotFoundError` or `ImportError` because `scripts/ci_classify.py` does not exist.

- [ ] **Step 3: Implement the map and `classify`**

`scripts/ci_classify.py` uses only the standard library. Data:

```python
SHARD_ORDER = (
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
)

SHARD_FILES = {
    "s3": (
        "test_s3_renderer_terraform.py",
        "test_s3_golden_real_tool_eval.py",
        "test_s3_workflow_integration.py",
        "test_s3_workflow_persistence.py",
    ),
    "sqs": (
        "test_sqs_renderer_terraform.py",
        "test_sqs_golden_real_tool_eval.py",
        "test_sqs_workflow_integration.py",
        "test_sqs_workflow_persistence.py",
        "test_sqs_workflow_hitl.py",
    ),
    "dynamodb": (
        "test_dynamodb_renderer_terraform.py",
        "test_dynamodb_golden_real_tool_eval.py",
        "test_dynamodb_workflow_integration.py",
        "test_dynamodb_workflow_persistence.py",
    ),
    "ecr": (
        "test_ecr_renderer_terraform.py",
        "test_ecr_golden_real_tool_eval.py",
        "test_ecr_workflow_persistence.py",
    ),
    "lambda": (
        "test_lambda_renderer_terraform.py",
        "test_lambda_golden_real_tool_eval.py",
        "test_lambda_workflow_integration.py",
        "test_lambda_workflow_persistence.py",
    ),
    "api_gateway": ("test_api_gateway_renderer_terraform.py",),
    "api_lambda": (
        "test_api_lambda_renderer_terraform.py",
        "test_api_lambda_golden_real_tool_eval.py",
        "test_api_lambda_workflow_integration.py",
        "test_api_lambda_workflow_persistence.py",
    ),
    "api_lambda_dynamodb": (
        "test_api_lambda_dynamodb_renderer_terraform.py",
        "test_api_lambda_dynamodb_golden_real_tool_eval.py",
        "test_api_lambda_dynamodb_workflow_persistence.py",
    ),
    "serverless_worker": (
        "test_serverless_worker_renderer_terraform.py",
        "test_serverless_worker_golden_real_tool_eval.py",
        "test_serverless_worker_workflow_integration.py",
        "test_serverless_worker_workflow_persistence.py",
        "test_application_composition.py",
        "test_cli_real_tool.py",
    ),
    "security": (
        "test_checkov_integration.py",
        "test_security_gate_integration.py",
        "test_platform_policy_integration.py",
        "test_plan_analyzer_integration.py",
        "test_terraform_runner_integration.py",
    ),
}

SHARD_CONSUMES = {
    "s3": frozenset({"s3"}),
    "sqs": frozenset({"sqs"}),
    "dynamodb": frozenset({"dynamodb"}),
    "ecr": frozenset({"ecr"}),
    "lambda": frozenset({"lambda"}),
    "api_gateway": frozenset({"api_gateway"}),
    "api_lambda": frozenset({"api_gateway", "lambda"}),
    "api_lambda_dynamodb": frozenset({"api_gateway", "lambda", "dynamodb"}),
    "serverless_worker": frozenset({"sqs", "lambda", "dynamodb"}),
    "security": frozenset({"sqs"}),
}
```

Prefix rows, longest match first is unnecessary if every prefix ends with `/` and the unknown module path does not share a listed prefix:

- `terraform/modules/<name>/` and `src/iac_agent/providers/aws/<provider_dir>/` for `s3`, `sqs`, `dynamodb`, `ecr`, `api_gateway`
- `src/iac_agent/providers/aws/lambda_function/` maps to module `lambda`
- `tests/terraform/s3/` and `tests/terraform/sqs/`
- composition directories map to that shard directly, not through a module
- exact file `src/iac_agent/providers/aws/kms.py` maps to modules `s3` and `sqs`

Selecting a module selects every shard whose `SHARD_CONSUMES` contains it.

These paths set `full=True` and select every shard, without forcing bootstrap or frontend:

- `src/iac_agent/graph/`
- `src/iac_agent/execution/`
- `src/iac_agent/security/`
- `src/iac_agent/policies/`
- `src/iac_agent/app/`
- `src/iac_agent/providers/aws/renderer.py`
- `src/iac_agent/providers/aws/resource.py`
- `src/iac_agent/providers/aws/terraform_render.py`
- `src/iac_agent/providers/aws/__init__.py`

`.github/workflows/` returns immediately with every shard, `bootstrap=True`, `frontend=True`, `full=True`, reason `workflow`.

`failed=True`, `paths is None`, or `paths == []` return that same failure selection, reason `classifier-failure`.

`docs/` and `README.md` add no shards. `ui/` sets `frontend=True`. `bootstrap/aws-oidc/` and the exact bootstrap test path set `bootstrap=True`.

A basename in `SHARD_FILES` selects only that shard. Any other path selects every shard with `bootstrap` and `frontend` left to the rest of the diff.

A diff walks every path. One workflow path or failure flag replaces the whole result with the failure selection. Otherwise shards are unioned, and `full` is true when every shard is selected.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/unit/ci/test_validation_classifier.py -v`

Expected: PASS. Then `ruff check scripts/ci_classify.py tests/unit/ci/test_validation_classifier.py`.

- [ ] **Step 5: Commit**

```bash
git add scripts/ci_classify.py tests/unit/ci/test_validation_classifier.py
git commit -m "$(cat <<'EOF'
test: lock blast-radius shard ownership

The classifier map is the only dependency graph. Unknown paths and
classifier failure select every real-tool shard.
EOF
)"
```

---

### Task 3: Classifier CLI

**Files:**
- Modify: `scripts/ci_classify.py`
- Modify: `tests/unit/ci/test_validation_classifier.py`

**Interfaces:**
- Consumes: `classify` and `Selection` from Task 2
- Produces: `format_github_output(selection: Selection) -> str`, `format_summary(selection: Selection, paths: list[str]) -> str`, `main(argv: list[str]) -> int`

- [ ] **Step 1: Write the failing CLI tests**

```python
def test_github_output_emits_one_boolean_per_shard(tmp_path: Path):
    module = _load()
    selection = module.classify(["terraform/modules/s3/main.tf"])
    text = module.format_github_output(selection)
    assert "s3=true" in text
    assert "sqs=false" in text
    assert "bootstrap=false" in text
    assert "frontend=false" in text
    assert "full=false" in text


def test_cli_writes_output_and_exits_zero(tmp_path: Path):
    module = _load()
    paths = tmp_path / "paths.txt"
    paths.write_text("terraform/modules/ecr/main.tf\n")
    output = tmp_path / "github.txt"
    summary = tmp_path / "summary.md"
    code = module.main(
        [
            "--paths-file",
            str(paths),
            "--github-output",
            str(output),
            "--step-summary",
            str(summary),
        ]
    )
    assert code == 0
    assert "ecr=true" in output.read_text()
    assert "s3=false" in output.read_text()
    assert "ecr" in summary.read_text()


def test_cli_missing_paths_file_exits_nonzero(tmp_path: Path):
    code = _load().main(["--paths-file", str(tmp_path / "missing.txt")])
    assert code == 2
```

- [ ] **Step 2: Run the new tests and confirm they fail**

Run: `pytest tests/unit/ci/test_validation_classifier.py::test_github_output_emits_one_boolean_per_shard tests/unit/ci/test_validation_classifier.py::test_cli_writes_output_and_exits_zero tests/unit/ci/test_validation_classifier.py::test_cli_missing_paths_file_exits_nonzero -v`

Expected: FAIL with `AttributeError` on `format_github_output` or `main`.

- [ ] **Step 3: Implement the CLI**

`format_github_output` writes one `name=true|false` line for each `SHARD_ORDER` entry, then `bootstrap`, `frontend`, and `full`.

`format_summary` is markdown listing selected shards, skipped shards, bootstrap, frontend, and `selection.reasons`.

`main` uses `argparse`. `--paths-file` is required. A missing file returns 2. `--unreadable` calls `classify(None)`. An empty file calls `classify([])`. Otherwise it classifies the stripped non-empty lines. Exit 0 after writing the output files when those flags are present.

Do not catch unexpected exceptions. A traceback fails the Classify job, and Task 9 treats that job failure as run-every-shard.

- [ ] **Step 4: Run the classifier tests**

Run: `pytest tests/unit/ci/test_validation_classifier.py -v && ruff check scripts/ci_classify.py tests/unit/ci/test_validation_classifier.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/ci_classify.py tests/unit/ci/test_validation_classifier.py
git commit -m "$(cat <<'EOF'
feat: add the CI validation classifier CLI

Report booleans and a step summary from the ownership map. A missing
path list fails the process so the workflow can fail closed later.
EOF
)"
```

---

### Task 4: Report-only Classify job

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `tests/unit/ci/test_validation_jobs.py`
- Modify: `docs/ci.md`

**Interfaces:**
- Consumes: `main` from Task 3
- Produces: job key `classify`, display name `Classify`, outputs for every `SHARD_ORDER` name plus `bootstrap`, `frontend`, and `full`. No other job reads those outputs yet.

- [ ] **Step 1: Write the failing structural test**

The file starts with `from pathlib import Path` and `import yaml`. `_jobs` and `_text` are module-level helpers reused by later tasks in this file.

```python
def _jobs() -> dict:
    loaded = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())
    return loaded["jobs"]


def _text() -> str:
    return Path(".github/workflows/ci.yml").read_text()


def test_classify_job_always_runs_and_does_not_gate_others():
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
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `pytest tests/unit/ci/test_validation_jobs.py::test_classify_job_always_runs_and_does_not_gate_others -v`

Expected: FAIL with `KeyError: 'classify'`.

- [ ] **Step 3: Add the job**

Append this job. Do not add `needs` or `if` to existing jobs. Pass SHAs through the environment, matching the attribution step.

```yaml
  classify:
    name: Classify
    runs-on: ubuntu-24.04
    outputs:
      s3: ${{ steps.result.outputs.s3 }}
      sqs: ${{ steps.result.outputs.sqs }}
      dynamodb: ${{ steps.result.outputs.dynamodb }}
      ecr: ${{ steps.result.outputs.ecr }}
      lambda: ${{ steps.result.outputs.lambda }}
      api_gateway: ${{ steps.result.outputs.api_gateway }}
      api_lambda: ${{ steps.result.outputs.api_lambda }}
      api_lambda_dynamodb: ${{ steps.result.outputs.api_lambda_dynamodb }}
      serverless_worker: ${{ steps.result.outputs.serverless_worker }}
      security: ${{ steps.result.outputs.security }}
      bootstrap: ${{ steps.result.outputs.bootstrap }}
      frontend: ${{ steps.result.outputs.frontend }}
      full: ${{ steps.result.outputs.full }}
    steps:
      - name: Check out repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Classify changed paths
        id: result
        env:
          EVENT_NAME: ${{ github.event_name }}
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          BEFORE_SHA: ${{ github.event.before }}
          AFTER_SHA: ${{ github.sha }}
        run: |
          set -euo pipefail
          paths="$RUNNER_TEMP/paths.txt"
          if [ "$EVENT_NAME" = "pull_request" ]; then
            git diff --name-only "$BASE_SHA"...HEAD > "$paths"
          elif [ "$BEFORE_SHA" = "0000000000000000000000000000000000000000" ]; then
            python scripts/ci_classify.py --unreadable --github-output "$GITHUB_OUTPUT" --step-summary "$GITHUB_STEP_SUMMARY"
            exit 0
          else
            git diff --name-only "$BEFORE_SHA" "$AFTER_SHA" > "$paths"
          fi
          python scripts/ci_classify.py --paths-file "$paths" --github-output "$GITHUB_OUTPUT" --step-summary "$GITHUB_STEP_SUMMARY"
```

`git diff` failure must fail the step. Task 9 treats a failed Classify job as full validation. Do not hide a diff error behind a successful empty classification.

Document in `docs/ci.md`: Classify always runs, writes a summary, and does not skip any job.

- [ ] **Step 4: Run the unit tests**

Run: `pytest tests/unit/ci -v && ruff check tests/unit/ci scripts/ci_classify.py`

Expected: PASS, with the existing aws-plan xfail tests still xfail.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml tests/unit/ci/test_validation_jobs.py docs/ci.md
git commit -m "$(cat <<'EOF'
ci: report validation domains without skipping jobs

Classify records which shards a diff would run. Tool Validation still
executes the full real-tool suite.
EOF
)"
```

### Checkpoint B

Stop. Push and open a pull request only if the human asks. Otherwise leave the branch local and stop.

When a GitHub Actions run exists for this commit, read the Classify step summary. Confirm Tool Validation still runs `pytest -m real_tool` and is not skipped. Do not start Task 5 until that run is green or the human has waived the remote run.

Record the run id in the session notes. Do not claim a wall-clock improvement.

---

### Task 5: Bootstrap Validation

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/unit/ci/test_validation_jobs.py`
- Modify: `docs/ci.md`

**Interfaces:**
- Consumes: existing `tests/integration/test_bootstrap_aws_oidc_terraform.py`
- Produces: job key `bootstrap-validation`, display name `Bootstrap Validation`, unconditional in this task

- [ ] **Step 1: Write the failing test**

```python
def test_bootstrap_validation_is_credential_free_and_unconditional():
    job = _jobs()["bootstrap-validation"]
    assert job["name"] == "Bootstrap Validation"
    assert job["runs-on"] == "ubuntu-24.04"
    assert "if" not in job
    script = "\n".join(step.get("run", "") for step in job["steps"])
    assert "pytest -m real_bootstrap_tool" in script
    assert "terraform apply" not in script
    assert "terraform destroy" not in script
    text = _text()
    assert "AWS_ACCESS_KEY_ID" not in text
    assert "id-token" not in text
    assert "aws-plan" not in _jobs()
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `pytest tests/unit/ci/test_validation_jobs.py::test_bootstrap_validation_is_credential_free_and_unconditional -v`

Expected: FAIL with `KeyError: 'bootstrap-validation'`.

- [ ] **Step 3: Add the job**

Mirror Tool Validation's checkout, Python 3.12, `pip install -e ".[dev]"`, and Terraform 1.16.1 steps. Do not install Checkov. The command is `pytest -m real_bootstrap_tool`. No AWS credentials, no `id-token`, no `terraform apply`, no `terraform destroy`. `Quality` and Tool Validation stay unchanged.

`docs/ci.md` gains a Bootstrap Validation section: the job runs the existing credential-free bootstrap plan test, does not call AWS, and does not change the module.

- [ ] **Step 4: Run structural tests**

Run: `pytest tests/unit/ci -v`

Expected: PASS, aws-plan tests still xfail.

Local proof, only if `terraform` is on `PATH` and the registry is reachable:

Run: `pytest -m real_bootstrap_tool -v`

Expected: 2 passed. This contacts the Terraform Registry for provider download and does not call AWS. If the sandbox blocks the registry, record that and rely on the GitHub job at Checkpoint C. Do not point the test at a real account.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml tests/unit/ci/test_validation_jobs.py docs/ci.md
git commit -m "$(cat <<'EOF'
ci: run credential-free bootstrap validation

CI now executes the existing bootstrap plan test. Tool Validation is
unchanged and the bootstrap module is not modified.
EOF
)"
```

---

### Task 6: Pin Checkov in the pip cache inputs

**Files:**
- Create: `ci/requirements-checkov.txt`
- Modify: `.github/workflows/ci.yml` Tool Validation install step only
- Modify: `tests/unit/ci/test_validation_jobs.py`

**Interfaces:**
- Consumes: Tool Validation's current `pip install checkov==3.3.13`
- Produces: `ci/requirements-checkov.txt` containing exactly `checkov==3.3.13`, and Tool Validation installing that file with `cache-dependency-path` covering `pyproject.toml` and `ci/requirements-checkov.txt`

- [ ] **Step 1: Write the failing test**

```python
def test_checkov_pin_is_a_requirements_file():
    pin = Path("ci/requirements-checkov.txt").read_text().strip()
    assert pin == "checkov==3.3.13"
    tool = _jobs()["tool-validation"]
    setup = next(step for step in tool["steps"] if step.get("uses", "").startswith("actions/setup-python@"))
    assert "ci/requirements-checkov.txt" in setup["with"]["cache-dependency-path"]
    script = "\n".join(step.get("run", "") for step in tool["steps"])
    assert "pip install -r ci/requirements-checkov.txt" in script
    assert "pip install checkov==" not in script
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `pytest tests/unit/ci/test_validation_jobs.py::test_checkov_pin_is_a_requirements_file -v`

Expected: FAIL because the requirements file is absent.

- [ ] **Step 3: Add the file and point Tool Validation at it**

`ci/requirements-checkov.txt` is one line: `checkov==3.3.13`.

On Tool Validation's setup-python step add:

```yaml
cache-dependency-path: |
  pyproject.toml
  ci/requirements-checkov.txt
```

Replace `pip install checkov==3.3.13` with `pip install -r ci/requirements-checkov.txt`. Leave `pytest -m real_tool` in place.

- [ ] **Step 4: Run the structural tests**

Run: `pytest tests/unit/ci -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ci/requirements-checkov.txt .github/workflows/ci.yml tests/unit/ci/test_validation_jobs.py
git commit -m "$(cat <<'EOF'
ci: hash the Checkov pin into the pip cache

Tool Validation installs the same 3.3.13 pin from a requirements file
so a pin change misses the cache.
EOF
)"
```

### Checkpoint C

Stop. Bootstrap Validation and Tool Validation both exist. Neither is conditional.

On the next GitHub run, both jobs must be green. Bootstrap Validation must not print an AWS account id or a role ARN from STS. If Bootstrap Validation calls AWS or fails closed on credentials, stop and keep the job; do not edit the module.

---

### Task 7: Reuse a runner-provided plugin cache

**Files:**
- Modify: `tests/integration/conftest.py`
- Create: `tests/unit/test_tf_plugin_cache_dir.py`

**Interfaces:**
- Consumes: session fixture `tf_plugin_cache_dir`
- Produces: `resolve_plugin_cache_dir(env_value: str | None, factory: pytest.TempPathFactory) -> Path`. The fixture calls it. When `TF_PLUGIN_CACHE_DIR` is set, that directory is created if needed and returned. Otherwise the fixture keeps `tmp_path_factory.mktemp("tf-plugin-cache", numbered=False)`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from tests.integration.conftest import resolve_plugin_cache_dir


def test_existing_env_dir_is_reused(tmp_path: Path):
    target = tmp_path / "cache"
    resolved = resolve_plugin_cache_dir(str(target), factory=None)
    assert resolved == target
    assert target.is_dir()


def test_missing_env_uses_the_factory(tmp_path: Path):
    class Factory:
        def mktemp(self, name: str, numbered: bool = True) -> Path:
            assert name == "tf-plugin-cache"
            assert numbered is False
            path = tmp_path / name
            path.mkdir()
            return path

    resolved = resolve_plugin_cache_dir(None, Factory())
    assert resolved == tmp_path / "tf-plugin-cache"
```

Importing `tests.integration.conftest` is valid because pytest puts the repo root on `sys.path`.

- [ ] **Step 2: Run it and confirm it fails**

Run: `pytest tests/unit/test_tf_plugin_cache_dir.py -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the helper and call it from the fixture**

Do not change `TerraformRunner`. The real-tool fixture already passes `TF_PLUGIN_CACHE_DIR` through `terraform_test_env`. The bootstrap test does not use this fixture and keeps its own overrides.

- [ ] **Step 4: Run the unit test and a deterministic subset**

Run: `pytest tests/unit/test_tf_plugin_cache_dir.py tests/unit/ci -v`

Expected: PASS. Do not run `pytest -m real_tool` in this task.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/conftest.py tests/unit/test_tf_plugin_cache_dir.py
git commit -m "$(cat <<'EOF'
test: reuse TF_PLUGIN_CACHE_DIR when CI provides one

Local runs still get a pytest temp cache. A shard runner can seed a
private directory without sharing it across jobs.
EOF
)"
```

---

### Task 8: Real-tool setup action and main-only cache save

**Files:**
- Create: `.github/actions/real-tool-setup/action.yml`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/unit/ci/test_validation_jobs.py`

**Interfaces:**
- Consumes: `ci/requirements-checkov.txt`, `resolve_plugin_cache_dir`
- Produces: composite action input `pytest-args`. Job key `provider-cache`, display name `Provider Cache`, `if: github.event_name == 'push' && github.ref == 'refs/heads/main'`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `pytest tests/unit/ci/test_validation_jobs.py::test_real_tool_setup_restores_and_does_not_save tests/unit/ci/test_validation_jobs.py::test_provider_cache_saves_only_on_main_push -v`

Expected: FAIL because the action and job do not exist.

- [ ] **Step 3: Add the action and the save job**

`.github/actions/real-tool-setup/action.yml`:

- `actions/setup-python@v5` with Python 3.12, `cache: pip`, and `cache-dependency-path` covering `pyproject.toml` and `ci/requirements-checkov.txt`
- `pip install -e ".[dev]"` and `pip install -r ci/requirements-checkov.txt`
- `hashicorp/setup-terraform@v3` at `1.16.1` with `terraform_wrapper: false`
- `actions/cache/restore@v4` path `${{ runner.temp }}/provider-restore`, key `tf-1.16.1-aws-6-${{ hashFiles('terraform/modules/**/versions.tf', 'bootstrap/aws-oidc/versions.tf') }}`
- copy that directory into `${{ runner.temp }}/tf-plugin-cache` when the restore directory exists, always `mkdir` the private directory, and append `TF_PLUGIN_CACHE_DIR` to `GITHUB_ENV`
- run `${{ inputs.pytest-args }}` with `AWS_EC2_METADATA_DISABLED=true`
- no save step and no AWS keys

`provider-cache` checks out the repo, sets up Terraform 1.16.1, restores the same key, copies `terraform/modules/s3` to `$RUNNER_TEMP/s3-init`, exports `TF_PLUGIN_CACHE_DIR=$RUNNER_TEMP/tf-plugin-cache` and `AWS_EC2_METADATA_DISABLED=true`, runs `terraform init -backend=false` in that copy, and saves the private cache with `actions/cache/save@v4` only when the restore step's `cache-hit` is not `true`. The save step's `if` is that cache-miss condition. The job itself already cannot run on a pull request.

Tool Validation's install and Terraform steps are replaced by checkout plus this action with `pytest-args: pytest -m real_tool`. The job stays unconditional. It does not save the cache.

- [ ] **Step 4: Run structural tests**

Run: `pytest tests/unit/ci -v && ruff check tests/unit/ci`

Expected: PASS. `test_frontend_job.py` still sees `pytest -m real_tool`.

- [ ] **Step 5: Commit**

```bash
git add .github/actions/real-tool-setup/action.yml .github/workflows/ci.yml tests/unit/ci/test_validation_jobs.py
git commit -m "$(cat <<'EOF'
ci: restore a private Terraform provider cache

Pull requests can restore the provider but cannot save it. Only a main
push populates the cache, from one job.
EOF
)"
```

---

### Task 9: Conditional shards beside Tool Validation

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/unit/ci/test_validation_jobs.py`
- Modify: `docs/ci.md`

**Interfaces:**
- Consumes: Classify outputs and the real-tool setup action
- Produces: ten shard jobs. Each `needs: classify`. Each `if` is `${{ !cancelled() && (needs.classify.result != 'success' || needs.classify.outputs.NAME == 'true') }}` where `NAME` is that shard's output. Tool Validation has no `if`.

Job keys and display names:

| Key | Name | Pytest files |
| --- | --- | --- |
| `shard-s3` | Terraform — S3 | the four `SHARD_FILES["s3"]` names |
| `shard-sqs` | Terraform — SQS | the five SQS names |
| `shard-dynamodb` | Terraform — DynamoDB | the four DynamoDB names |
| `shard-ecr` | Terraform — ECR | the three ECR names |
| `shard-lambda` | Terraform — Lambda | the four Lambda names |
| `shard-api-gateway` | Terraform — API Gateway | `test_api_gateway_renderer_terraform.py` |
| `shard-api-lambda` | Terraform — API Lambda | the four API Lambda names |
| `shard-api-lambda-dynamodb` | Terraform — API Lambda DynamoDB | the three API Lambda DynamoDB names |
| `shard-serverless-worker` | Terraform — Serverless Worker | the six serverless-worker names, including `test_application_composition.py` and `test_cli_real_tool.py` |
| `shard-security` | Security Validation | the five security names |

Pytest arguments are `pytest -m real_tool` plus `tests/integration/<file>` for each owned file. The marker and the file list both stay, so a file that loses the marker is not executed as an unmarked test.

- [ ] **Step 1: Write the failing tests**

Assert all ten keys exist, display names match, each `if` equals the expression above for that output name, and none of those `if` strings contain `terraform/modules` or `serverless_worker/` as a path condition.

```python
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
    action = next(step for step in tool_steps if str(step.get("uses", "")).startswith("./.github/actions/real-tool-setup"))
    assert action["with"]["pytest-args"] == "pytest -m real_tool"
```

Also assert `shard-s3` does not list `test_sqs_renderer_terraform.py` and `shard-sqs` does not list `test_lambda_renderer_terraform.py`.

Frontend and Bootstrap Validation gain the same fail-closed `if`, with outputs `frontend` and `bootstrap`, and `needs: classify`. `quality` and `tests` still have no `if`.

- [ ] **Step 2: Run the test and confirm it fails**

Run: `pytest tests/unit/ci/test_validation_jobs.py::test_shard_conditions_only_read_classifier_outputs -v`

Expected: FAIL because `shard-s3` is absent.

- [ ] **Step 3: Add the jobs and gate Frontend and Bootstrap Validation**

Each shard job is checkout plus the composite action. No shard contains a copy of the module graph.

Update `docs/ci.md` to say shards run beside Tool Validation, and a failed Classify job runs every shard, Bootstrap Validation, and Frontend.

- [ ] **Step 4: Run structural tests**

Run: `pytest tests/unit/ci tests/unit/test_tf_plugin_cache_dir.py -v && ruff check tests/unit/ci scripts/ci_classify.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml tests/unit/ci/test_validation_jobs.py docs/ci.md
git commit -m "$(cat <<'EOF'
ci: run real-tool shards beside Tool Validation

Shard jobs follow classifier outputs and fail closed when Classify
fails. The monolithic suite still runs on the same revision.
EOF
)"
```

### Checkpoint D

Stop. Do not delete Tool Validation.

This commit is the equivalence revision. It contains both the monolith and the shards. The next session only records evidence. It does not edit `ci.yml` until Checkpoint E passes.

---

### Task 10: Equivalence evidence

**Files:**
- Modify: `docs/ci.md` only if a human has already captured a green run and asks to record the run id. Otherwise this task changes no files.

**Interfaces:**
- Consumes: the Checkpoint D commit SHA
- Produces: a written evidence note in the session, not a guessed timing table

- [ ] **Step 1: Confirm the parent workflow still has both suites**

Run: `python - <<'PY'
from pathlib import Path
import yaml
jobs = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())["jobs"]
assert "tool-validation" in jobs
assert "shard-s3" in jobs and "shard-security" in jobs
print("both suites present")
PY`

Expected: `both suites present`.

- [ ] **Step 2: Run the static union tests**

Run: `pytest tests/unit/ci/test_validation_classifier.py -v`

Expected: PASS, including one-owner and no-omission tests.

- [ ] **Step 3: Read the GitHub Actions run for this SHA**

Use `gh run list --commit <checkpoint-d-sha> --workflow ci.yml` and `gh run view <id> --json jobs`. Do not start a real AWS plan. Do not print tokens.

Required evidence, all on that same run:

1. Tool Validation conclusion is `success`. Its log contains `79 passed` and `2 skipped`, or you stop if the counts differ and investigate before any deletion. The inventory is allowed to change only if this plan's commits added no real-tool tests. They do not.
2. Every shard job conclusion is `success` or `skipped`. Because this commit edits `.github/workflows/ci.yml`, Classify must select full validation, so every shard, Bootstrap Validation, and Frontend must be `success`, not `skipped`.
3. Sum of shard `passed` counts equals the Tool Validation `passed` count. Sum of shard `skipped` counts equals the Tool Validation `skipped` count. A shard log line looks like `N passed`.
4. No shard log contains `terraform apply` or `terraform destroy`.
5. Bootstrap Validation is `success` and its log does not contain `AssumeRole` or `GetCallerIdentity`.

- [ ] **Step 4: Measure wall clock**

From the job `startedAt` and `completedAt` timestamps, record:

- Tool Validation duration, compared with the baseline 15m 31s from run `37062242107` job `111021403734`
- pytest duration inside Tool Validation if the log still reports it, baseline 14m 59s
- each shard duration
- the critical path: the maximum shard duration, plus its job name

Write those numbers in the session report. If the run does not exist, the numbers are "not measured". Do not substitute the design's 68s or 127s estimates.

- [ ] **Step 5: Decide**

If any item in Step 3 fails: stop. Leave Tool Validation in the workflow. Do not commit a deletion. Report which item failed.

If all five items pass: record the run URL and the counts. Only then is Task 11 allowed, in a later session.

This task has no commit when it only observes CI.

### Checkpoint E — equivalence gate

Tool Validation is removed only when all of these are true for one SHA that still contains the monolith:

1. Every current `real_tool` file is in exactly one shard, proven by `pytest tests/unit/ci/test_validation_classifier.py`.
2. The shard file union has no duplicate names, proven by that same test.
3. Every shard job passed on that SHA.
4. Tool Validation passed on that SHA.
5. Passed and skipped totals match between the monolith and the sum of the shards.

Otherwise stop and keep Tool Validation.

---

### Task 11: Remove monolithic Tool Validation

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/unit/ci/test_validation_jobs.py`
- Modify: `tests/unit/ci/test_frontend_job.py`
- Modify: `docs/ci.md`

**Interfaces:**
- Consumes: Checkpoint E evidence
- Produces: no `tool-validation` job. Shard commands still contain `pytest -m real_tool` plus file paths. `Quality` and `Tests` names unchanged.

- [ ] **Step 1: Stop if the evidence is missing**

If the session cannot cite the Checkpoint E run URL, passed count, skipped count, and critical-path shard, do not edit files. Stop.

- [ ] **Step 2: Update tests first**

Change `test_frontend_job.py` so it still requires the deterministic marker string, and requires `pytest -m real_tool tests/integration/` rather than a bare `pytest -m real_tool` line that was the monolith.

Add:

```python
def test_monolithic_tool_validation_job_is_gone():
    assert "tool-validation" not in _jobs()
    assert all(job["name"] != "Tool Validation" for job in _jobs().values())
```

Update the Task 4 assertion that required `tool-validation` to require the ten shard keys instead.

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `pytest tests/unit/ci/test_validation_jobs.py::test_monolithic_tool_validation_job_is_gone -v`

Expected: FAIL because the job still exists.

- [ ] **Step 4: Delete the job**

Remove the `tool-validation` job only. Leave Classify, the shards, Bootstrap Validation, Provider Cache, Quality, Tests, and Frontend. Do not rename Quality or Tests. Do not edit branch protection.

`docs/ci.md` describes shards as the real-tool suite and states the equivalence run URL recorded at Checkpoint E. It does not say the suite was reduced.

- [ ] **Step 5: Run structural tests**

Run: `pytest tests/unit/ci tests/unit/test_tf_plugin_cache_dir.py tests/unit/ci/test_validation_classifier.py -v && ruff check tests/unit/ci scripts/ci_classify.py`

Expected: PASS. aws-plan xfails still xfail.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/ci.yml tests/unit/ci/test_validation_jobs.py tests/unit/ci/test_frontend_job.py docs/ci.md
git commit -m "$(cat <<'EOF'
ci: drop monolithic Tool Validation after shard equivalence

The shard union matched the real-tool inventory on the recorded run.
Quality and Tests stay the required checks.
EOF
)"
```

Replace the message body with the recorded run id before committing, so the commit says which run proved equivalence. If that id is not available, do not commit.

### Checkpoint F

Stop. The following GitHub run no longer has a monolith to compare. Its success means the shard workflow is green, not that equivalence was re-proven. Equivalence stays the Checkpoint E record.

Do not open a pull request, push, or change rulesets unless the human asks.

---

## Performance measurement

Baseline, already measured, not an estimate:

| Item | Value |
| --- | --- |
| Run | `37062242107` |
| Job | `111021403734` Tool Validation |
| Job wall clock | 15m 31s |
| `pytest -m real_tool` | 14m 59s |
| Inventory | 39 files, 79 passed, 2 skipped |

After Checkpoint D, compute durations from GitHub `startedAt` and `completedAt`. The new wall clock for product validation is the slowest shard job on that run, not the sum, and not the design-doc estimate. Report:

- baseline Tool Validation wall clock: 15m 31s
- this run's Tool Validation wall clock
- this run's slowest shard name and duration
- whether that shard is the critical path

No performance claim is valid before those timestamps exist.

## Security checks on every phase

- `pytest tests/unit/ci/test_aws_plan_workflow_structure.py` stays xfail for job existence and passes the `id-token` absence test.
- Workflow text has no `terraform apply`, `terraform destroy`, `AWS_ACCESS_KEY_ID`, or `id-token`.
- `bootstrap/aws-oidc/` is not in the diff.
- No ruleset API calls.

## Rollback

| Phase | Recovery |
| --- | --- |
| 1 | Revert the ubuntu pin commit. Runners return to `ubuntu-latest`. |
| 2 | Revert the classifier commits. No job was skipped, so main's validation set is unchanged. |
| 3 | Revert the Bootstrap Validation commit. The gap returns to today's skipped test. Tool Validation remains. |
| 4 | Revert the shard commit. Tool Validation still runs the full suite. |
| 5 | No commit. A failed gate means do not start Task 11. |
| 6 | Revert the removal commit. Tool Validation returns beside the shards. |

## Acceptance checklist

- [ ] `ubuntu-24.04` is pinned and action majors already in the file are unchanged.
- [ ] Classifier tests cover one owner, union equality, no duplicates, SQS, Lambda, DynamoDB, API Gateway, S3, ECR, `kms.py`, transitive consumers, unrelated shards excluded, unknown paths, new module directories, empty diff, unreadable diff, classifier failure, workflow paths, and mixed diffs.
- [ ] Workflow `if` expressions read classifier outputs only.
- [ ] Classify failure runs every shard, Bootstrap Validation, and Frontend.
- [ ] Unknown product paths run every shard and do not by themselves run Bootstrap Validation or Frontend.
- [ ] Docs-only runs Quality, Tests, and Classify.
- [ ] Bootstrap Validation runs `pytest -m real_bootstrap_tool` with no AWS credentials in YAML.
- [ ] No `aws-plan` job was added.
- [ ] Tool Validation remained until Checkpoint E passed.
- [ ] Checkpoint E cites one run URL where monolith and shard totals match.
- [ ] The critical-path shard is named from that run's timestamps.
- [ ] Required checks were not edited.
- [ ] No apply, destroy, IAM, or OIDC edit is in the branch diff.
