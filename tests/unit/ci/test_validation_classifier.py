"""Blast-radius shard ownership.

Group A locks the approved shard-to-file table against the real-tool tree.
Those tests do not import the classifier. Group B loads ``scripts/ci_classify.py``
inside each test and stays red until that module exists.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_CLASSIFIER = Path("scripts/ci_classify.py")

EXPECTED_SHARD_ORDER = (
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

EXPECTED_SHARD_FILES = {
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

_OTHER_THAN_S3 = {
    "lambda",
    "dynamodb",
    "api_gateway",
    "api_lambda",
    "api_lambda_dynamodb",
    "sqs",
    "ecr",
    "serverless_worker",
    "security",
}


def _owned_names() -> list[str]:
    return [name for files in EXPECTED_SHARD_FILES.values() for name in files]


def _assert_exact_ownership(real_tool_files: set[str]) -> None:
    assert tuple(EXPECTED_SHARD_FILES) == EXPECTED_SHARD_ORDER
    owned = _owned_names()
    duplicates = sorted(name for name in set(owned) if owned.count(name) > 1)
    assert duplicates == []
    assert set(owned) == real_tool_files
    for name in real_tool_files:
        owners = [shard for shard, files in EXPECTED_SHARD_FILES.items() if name in files]
        assert len(owners) == 1, name


def _marker_real_tool_files() -> set[str]:
    found = set()
    for path in (ROOT / "tests" / "integration").glob("test_*.py"):
        if "pytest.mark.real_tool" in path.read_text():
            found.add(path.name)
    return found


def _collected_real_tool_files() -> set[str]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", "real_tool"],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert completed.returncode == 0, completed.stderr
    files: set[str] = set()
    for line in completed.stdout.splitlines():
        if "::" not in line or not line.startswith("tests/integration/"):
            continue
        files.add(Path(line.split("::", 1)[0]).name)
    return files


def _load():
    path = ROOT / _CLASSIFIER
    if not path.is_file():
        raise ImportError(f"classifier module is missing: {_CLASSIFIER}")
    spec = importlib.util.spec_from_file_location("ci_classify", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"classifier module is missing: {_CLASSIFIER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fields(result) -> tuple:
    return (result.shards, result.bootstrap, result.frontend, result.full)


def _assert_selection(result, shards, *, bootstrap: bool, frontend: bool, full: bool) -> None:
    assert result.shards == frozenset(shards)
    assert result.bootstrap is bootstrap
    assert result.frontend is frontend
    assert result.full is full


class TestGroupAOwnershipContract:
    """Green without scripts/ci_classify.py. Expectation data is the contract."""

    def test_marker_real_tool_files_are_owned_by_exactly_one_shard(self):
        _assert_exact_ownership(_marker_real_tool_files())

    def test_collected_real_tool_files_are_owned_by_exactly_one_shard(self):
        _assert_exact_ownership(_collected_real_tool_files())

    def test_kms_importers_are_s3_and_sqs_contracts(self):
        root = ROOT / "src"
        needle = "from iac_agent.providers.aws.kms import validate_kms_key_id"
        importers = sorted(
            str(path.relative_to(ROOT))
            for path in root.rglob("*.py")
            if needle in path.read_text()
        )
        assert importers == [
            "src/iac_agent/providers/aws/s3/contract.py",
            "src/iac_agent/providers/aws/sqs/contract.py",
        ]

    def test_terraform_module_directories_are_the_six_families(self):
        names = sorted(
            path.name for path in (ROOT / "terraform" / "modules").iterdir() if path.is_dir()
        )
        assert names == ["api_gateway", "dynamodb", "ecr", "lambda", "s3", "sqs"]


class TestGroupBClassifyContract:
    """Red until scripts/ci_classify.py exists. Each test loads that file."""

    @pytest.mark.parametrize(
        ("path", "shards", "bootstrap", "frontend", "full"),
        [
            (
                "terraform/modules/sqs/main.tf",
                {"sqs", "serverless_worker", "security"},
                False,
                False,
                False,
            ),
            (
                "src/iac_agent/providers/aws/sqs/renderer.py",
                {"sqs", "serverless_worker", "security"},
                False,
                False,
                False,
            ),
            (
                "terraform/modules/lambda/main.tf",
                {"lambda", "api_lambda", "api_lambda_dynamodb", "serverless_worker"},
                False,
                False,
                False,
            ),
            (
                "terraform/modules/dynamodb/main.tf",
                {"dynamodb", "api_lambda_dynamodb", "serverless_worker"},
                False,
                False,
                False,
            ),
            (
                "terraform/modules/api_gateway/main.tf",
                {"api_gateway", "api_lambda", "api_lambda_dynamodb"},
                False,
                False,
                False,
            ),
            ("terraform/modules/s3/main.tf", {"s3"}, False, False, False),
            ("terraform/modules/ecr/main.tf", {"ecr"}, False, False, False),
            (
                "src/iac_agent/providers/aws/kms.py",
                {"s3", "sqs", "serverless_worker", "security"},
                False,
                False,
                False,
            ),
            (
                "src/iac_agent/compositions/serverless_worker/renderer.py",
                {"serverless_worker"},
                False,
                False,
                False,
            ),
            (
                "src/iac_agent/compositions/api_lambda/renderer.py",
                {"api_lambda"},
                False,
                False,
                False,
            ),
            (
                "src/iac_agent/compositions/api_lambda_dynamodb/renderer.py",
                {"api_lambda_dynamodb"},
                False,
                False,
                False,
            ),
            (
                "tests/integration/test_s3_renderer_terraform.py",
                {"s3"},
                False,
                False,
                False,
            ),
            ("docs/ci.md", set(), False, False, False),
            ("README.md", set(), False, False, False),
            ("ui/src/App.tsx", set(), False, True, False),
            ("bootstrap/aws-oidc/main.tf", set(), True, False, False),
        ],
    )
    def test_path_selection(self, path, shards, bootstrap, frontend, full):
        result = _load().classify([path])
        _assert_selection(
            result,
            shards,
            bootstrap=bootstrap,
            frontend=frontend,
            full=full,
        )

    def test_sqs_does_not_select_unrelated_families(self):
        result = _load().classify(["terraform/modules/sqs/main.tf"])
        assert result.shards == frozenset({"sqs", "serverless_worker", "security"})
        assert result.shards.isdisjoint({"s3", "ecr", "lambda"})

    def test_lambda_does_not_select_s3_or_ecr(self):
        result = _load().classify(["terraform/modules/lambda/main.tf"])
        assert result.shards == frozenset(
            {"lambda", "api_lambda", "api_lambda_dynamodb", "serverless_worker"}
        )
        assert result.shards.isdisjoint({"s3", "ecr"})

    def test_dynamodb_does_not_select_s3_or_sqs(self):
        result = _load().classify(["terraform/modules/dynamodb/main.tf"])
        assert result.shards == frozenset(
            {"dynamodb", "api_lambda_dynamodb", "serverless_worker"}
        )
        assert result.shards.isdisjoint({"s3", "sqs"})

    def test_api_gateway_selects_only_its_closure(self):
        result = _load().classify(["terraform/modules/api_gateway/main.tf"])
        assert result.shards == frozenset(
            {"api_gateway", "api_lambda", "api_lambda_dynamodb"}
        )
        assert result.bootstrap is False
        assert result.frontend is False
        assert result.full is False

    def test_s3_selects_s3_only(self):
        result = _load().classify(["terraform/modules/s3/main.tf"])
        assert result.shards == frozenset({"s3"})
        assert result.shards.isdisjoint(_OTHER_THAN_S3)
        assert result.bootstrap is False
        assert result.frontend is False
        assert result.full is False

    def test_ecr_selects_ecr_only(self):
        result = _load().classify(["terraform/modules/ecr/main.tf"])
        assert result.shards == frozenset({"ecr"})
        assert result.bootstrap is False
        assert result.frontend is False
        assert result.full is False

    def test_kms_does_not_select_lambda_dynamodb_ecr_or_api_gateway(self):
        result = _load().classify(["src/iac_agent/providers/aws/kms.py"])
        assert result.shards == frozenset({"s3", "sqs", "serverless_worker", "security"})
        assert result.shards.isdisjoint({"lambda", "dynamodb", "ecr", "api_gateway"})

    @pytest.mark.parametrize(
        ("path", "shard"),
        [
            ("src/iac_agent/compositions/serverless_worker/renderer.py", "serverless_worker"),
            ("src/iac_agent/compositions/api_lambda/renderer.py", "api_lambda"),
            (
                "src/iac_agent/compositions/api_lambda_dynamodb/renderer.py",
                "api_lambda_dynamodb",
            ),
        ],
    )
    def test_composition_directory_selects_only_that_shard(self, path, shard):
        result = _load().classify([path])
        _assert_selection(result, {shard}, bootstrap=False, frontend=False, full=False)

    def test_changed_real_tool_file_selects_only_its_owning_shard(self):
        result = _load().classify(["tests/integration/test_s3_renderer_terraform.py"])
        _assert_selection(result, {"s3"}, bootstrap=False, frontend=False, full=False)

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
            "src/iac_agent/intent/models.py",
            "terraform/modules/newfam/main.tf",
        ],
    )
    def test_shared_or_unknown_path_selects_every_shard_without_bootstrap_or_frontend(
        self, path
    ):
        module = _load()
        result = module.classify([path])
        assert result.shards == frozenset(module.SHARD_ORDER)
        assert result.full is True
        assert result.bootstrap is False
        assert result.frontend is False

    def test_empty_diff_selects_full_failure_set(self):
        module = _load()
        result = module.classify([])
        assert result.shards == frozenset(module.SHARD_ORDER)
        assert result.full is True
        assert result.bootstrap is True
        assert result.frontend is True

    def test_unreadable_diff_selects_full_failure_set(self):
        module = _load()
        result = module.classify(None)
        assert result.shards == frozenset(module.SHARD_ORDER)
        assert result.bootstrap is True
        assert result.frontend is True
        assert result.full is True

    def test_classifier_failure_flag_selects_full_failure_set(self):
        module = _load()
        result = module.classify(["docs/ci.md"], failed=True)
        assert result.shards == frozenset(module.SHARD_ORDER)
        assert result.full is True
        assert result.bootstrap is True
        assert result.frontend is True

    def test_workflow_path_selects_full_validation_plus_bootstrap_and_frontend(self):
        module = _load()
        result = module.classify([".github/workflows/ci.yml"])
        assert result.shards == frozenset(module.SHARD_ORDER)
        assert result.full is True
        assert result.bootstrap is True
        assert result.frontend is True

    def test_docs_plus_s3_is_only_s3(self):
        result = _load().classify(["docs/ci.md", "terraform/modules/s3/main.tf"])
        _assert_selection(result, {"s3"}, bootstrap=False, frontend=False, full=False)

    def test_ui_plus_s3_unions_frontend(self):
        result = _load().classify(["ui/src/App.tsx", "terraform/modules/s3/main.tf"])
        _assert_selection(result, {"s3"}, bootstrap=False, frontend=True, full=False)

    def test_docs_only_selects_nothing_extra(self):
        result = _load().classify(["docs/ci.md", "README.md"])
        _assert_selection(result, set(), bootstrap=False, frontend=False, full=False)

    def test_ui_only_selects_frontend_only(self):
        result = _load().classify(["ui/src/App.tsx"])
        _assert_selection(result, set(), bootstrap=False, frontend=True, full=False)

    def test_bootstrap_selects_bootstrap_only(self):
        result = _load().classify(["bootstrap/aws-oidc/main.tf"])
        _assert_selection(result, set(), bootstrap=True, frontend=False, full=False)

    def test_s3_and_ecr_select_only_those_shards(self):
        result = _load().classify(
            [
                "terraform/modules/s3/main.tf",
                "terraform/modules/ecr/main.tf",
            ]
        )
        _assert_selection(result, {"s3", "ecr"}, bootstrap=False, frontend=False, full=False)

    def test_sqs_and_s3_select_sqs_closure_union_s3(self):
        result = _load().classify(
            [
                "terraform/modules/sqs/main.tf",
                "terraform/modules/s3/main.tf",
            ]
        )
        _assert_selection(
            result,
            {"s3", "sqs", "serverless_worker", "security"},
            bootstrap=False,
            frontend=False,
            full=False,
        )

    def test_sqs_and_s3_path_order_does_not_change_the_result(self):
        module = _load()
        sqs = "terraform/modules/sqs/main.tf"
        s3 = "terraform/modules/s3/main.tf"
        assert _fields(module.classify([sqs, s3])) == _fields(module.classify([s3, sqs]))

    def test_duplicated_path_does_not_change_the_result(self):
        module = _load()
        s3 = "terraform/modules/s3/main.tf"
        assert _fields(module.classify([s3])) == _fields(module.classify([s3, s3]))

    def test_production_shard_files_match_ownership_contract(self):
        module = _load()
        assert module.SHARD_ORDER == EXPECTED_SHARD_ORDER
        assert module.SHARD_FILES == EXPECTED_SHARD_FILES

    def test_every_terraform_module_selects_a_shard_that_consumes_it(self):
        module = _load()
        names = sorted(
            path.name for path in (ROOT / "terraform" / "modules").iterdir() if path.is_dir()
        )
        for name in names:
            result = module.classify([f"terraform/modules/{name}/main.tf"])
            assert any(name in module.SHARD_CONSUMES[shard] for shard in result.shards)


class TestPathEvidenceAndReasons:
    """Locks the three verified paths and the stable reason tokens."""

    def test_lambda_function_provider_selects_lambda_module_closure(self):
        result = _load().classify(
            ["src/iac_agent/providers/aws/lambda_function/renderer.py"]
        )
        _assert_selection(
            result,
            {"lambda", "api_lambda", "api_lambda_dynamodb", "serverless_worker"},
            bootstrap=False,
            frontend=False,
            full=False,
        )

    def test_terraform_s3_fixture_selects_s3_only(self):
        result = _load().classify(["tests/terraform/s3/main.tf"])
        _assert_selection(result, {"s3"}, bootstrap=False, frontend=False, full=False)

    def test_terraform_sqs_fixture_selects_sqs_closure_only(self):
        result = _load().classify(["tests/terraform/sqs/main.tf"])
        assert result.shards == frozenset({"sqs", "serverless_worker", "security"})
        assert result.shards.isdisjoint({"s3", "ecr", "lambda"})
        assert result.bootstrap is False
        assert result.frontend is False
        assert result.full is False

    def test_bootstrap_integration_file_selects_bootstrap_only(self):
        result = _load().classify(
            ["tests/integration/test_bootstrap_aws_oidc_terraform.py"]
        )
        _assert_selection(result, set(), bootstrap=True, frontend=False, full=False)
        assert result.reasons == ("bootstrap change",)

    def test_s3_reason_is_direct_s3(self):
        result = _load().classify(["terraform/modules/s3/main.tf"])
        assert result.reasons == ("direct:s3",)

    def test_sqs_reasons_are_direct_plus_transitive(self):
        result = _load().classify(["terraform/modules/sqs/main.tf"])
        assert result.reasons == (
            "direct:sqs",
            "transitive:security",
            "transitive:serverless_worker",
        )

    def test_kms_reasons_name_both_direct_modules(self):
        result = _load().classify(["src/iac_agent/providers/aws/kms.py"])
        assert result.reasons == (
            "direct:s3",
            "direct:sqs",
            "transitive:security",
            "transitive:serverless_worker",
        )

    def test_real_tool_and_composition_reasons_are_direct_only(self):
        module = _load()
        real_tool = module.classify(["tests/integration/test_s3_renderer_terraform.py"])
        assert real_tool.reasons == ("direct:s3",)
        composition = module.classify(
            ["src/iac_agent/compositions/serverless_worker/renderer.py"]
        )
        assert composition.reasons == ("direct:serverless_worker",)

    @pytest.mark.parametrize(
        ("path", "reason"),
        [
            ("src/iac_agent/graph/workflow.py", "shared product path"),
            ("src/iac_agent/execution/terraform_runner.py", "shared product path"),
            ("src/iac_agent/security/checkov_profiles.py", "shared product path"),
            ("src/iac_agent/policies/platform.py", "shared product path"),
            ("src/iac_agent/app/composition.py", "shared product path"),
            ("src/iac_agent/providers/aws/renderer.py", "shared product path"),
            ("src/iac_agent/providers/aws/resource.py", "shared product path"),
            ("src/iac_agent/providers/aws/terraform_render.py", "shared product path"),
            ("src/iac_agent/providers/aws/__init__.py", "shared product path"),
            ("src/iac_agent/intent/models.py", "unknown path"),
            ("terraform/modules/newfam/main.tf", "unknown path"),
        ],
    )
    def test_shared_and_unknown_reasons(self, path, reason):
        result = _load().classify([path])
        assert result.reasons == (reason,)
        assert result.bootstrap is False
        assert result.frontend is False

    def test_empty_diff_reason(self):
        assert _load().classify([]).reasons == ("empty diff",)

    def test_unreadable_diff_reason(self):
        assert _load().classify(None).reasons == ("unreadable diff",)

    def test_classifier_failure_reason_ignores_docs(self):
        module = _load()
        assert module.classify(["docs/ci.md"], failed=True).reasons == (
            "classifier failure",
        )
        assert module.classify([], failed=True).reasons == ("classifier failure",)
        assert module.classify(None, failed=True).reasons == ("classifier failure",)

    def test_workflow_change_reason_replaces_other_paths(self):
        result = _load().classify(
            ["terraform/modules/s3/main.tf", ".github/workflows/ci.yml"]
        )
        assert result.reasons == ("workflow change",)
        assert result.shards == frozenset(_load().SHARD_ORDER)
        assert result.bootstrap is True
        assert result.frontend is True
        assert result.full is True

    def test_docs_plus_s3_reason_is_only_direct_s3(self):
        result = _load().classify(["docs/ci.md", "terraform/modules/s3/main.tf"])
        assert result.reasons == ("direct:s3",)

    def test_ui_plus_s3_reasons_omit_bootstrap(self):
        result = _load().classify(["ui/src/App.tsx", "terraform/modules/s3/main.tf"])
        assert result.reasons == ("direct:s3", "frontend change")
        assert "bootstrap change" not in result.reasons

    def test_reasons_do_not_depend_on_order_or_duplicates(self):
        module = _load()
        sqs = "terraform/modules/sqs/main.tf"
        s3 = "terraform/modules/s3/main.tf"
        expected = (
            "direct:s3",
            "direct:sqs",
            "transitive:security",
            "transitive:serverless_worker",
        )
        assert module.classify([sqs, s3]).reasons == expected
        assert module.classify([s3, sqs, sqs]).reasons == expected

    def test_normalized_separators_do_not_change_selection_or_reasons(self):
        module = _load()
        plain = module.classify(["terraform/modules/s3/main.tf"])
        dotted = module.classify(["./terraform/modules/s3/main.tf"])
        windows = module.classify(["terraform\\modules\\s3\\main.tf"])
        assert _fields(dotted) == _fields(plain)
        assert dotted.reasons == plain.reasons == ("direct:s3",)
        assert _fields(windows) == _fields(plain)
        assert windows.reasons == plain.reasons

    def test_shard_consumes_is_the_module_closure_table(self):
        assert _load().SHARD_CONSUMES == {
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


def test_github_output_emits_one_boolean_per_shard(tmp_path: Path):
    module = _load()
    selection = module.classify(["terraform/modules/s3/main.tf"])
    text = module.format_github_output(selection)
    assert "s3=true" in text
    assert "sqs=false" in text
    assert "bootstrap=false" in text
    assert "frontend=false" in text
    assert "full=false" in text
    assert "reasons=direct:s3" in text.splitlines()
    shard_lines = text.splitlines()[: len(module.SHARD_ORDER)]
    assert shard_lines == [
        f"{name}={'true' if name in selection.shards else 'false'}"
        for name in module.SHARD_ORDER
    ]


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
    summary_text = summary.read_text()
    assert "ecr" in summary_text
    assert "Selected shards:" in summary_text
    assert "Skipped shards:" in summary_text
    assert "direct:ecr" in summary_text


def test_cli_missing_paths_file_exits_nonzero(tmp_path: Path):
    output = tmp_path / "github.txt"
    code = _load().main(
        [
            "--paths-file",
            str(tmp_path / "missing.txt"),
            "--github-output",
            str(output),
        ]
    )
    assert code == 2
    assert not output.exists()


def test_cli_empty_file_is_empty_diff(tmp_path: Path):
    paths = tmp_path / "paths.txt"
    paths.write_text("")
    output = tmp_path / "github.txt"
    code = _load().main(
        ["--paths-file", str(paths), "--github-output", str(output)]
    )
    assert code == 0
    assert "reasons=empty diff" in output.read_text().splitlines()


def test_cli_unreadable_flag_classifies_none(tmp_path: Path):
    paths = tmp_path / "paths.txt"
    paths.write_text("docs/ci.md\n")
    output = tmp_path / "github.txt"
    code = _load().main(
        [
            "--paths-file",
            str(paths),
            "--unreadable",
            "--github-output",
            str(output),
        ]
    )
    assert code == 0
    text = output.read_text()
    assert "reasons=unreadable diff" in text.splitlines()
    assert "full=true" in text
    assert "bootstrap=true" in text


def test_cli_strips_blank_lines(tmp_path: Path):
    paths = tmp_path / "paths.txt"
    paths.write_text("\n  terraform/modules/s3/main.tf  \n\n")
    output = tmp_path / "github.txt"
    code = _load().main(
        ["--paths-file", str(paths), "--github-output", str(output)]
    )
    assert code == 0
    text = output.read_text()
    assert "s3=true" in text
    assert "reasons=direct:s3" in text.splitlines()
