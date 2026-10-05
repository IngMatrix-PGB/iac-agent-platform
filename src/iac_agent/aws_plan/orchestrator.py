"""Prepare, verify, and plan one canonical SQS proposal."""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

from iac_agent.aws_plan.binding import (
    PullRequestReader,
    ShaMismatch,
    bind_proposal,
    proposal_blob_paths,
)
from iac_agent.aws_plan.evidence import V3Evidence, write_evidence
from iac_agent.aws_plan.execution import ConfigurationError, v3_plan_env, v3_runner
from iac_agent.aws_plan.handoff import (
    HandoffManifest,
    HandoffRejected,
    verify_handoff,
    write_handoff,
)
from iac_agent.aws_plan.identity import AccountMismatch, verify_caller_identity
from iac_agent.aws_plan.outcomes import TerminalOutcome
from iac_agent.aws_plan.proposal import ProposalRejected, decode_sqs_proposal
from iac_agent.aws_plan.target import (
    AWS_ACCOUNT_ID,
    AWS_REGION,
    IAM_ROLE_ARN,
    REPOSITORY_ID,
)
from iac_agent.aws_plan.workspace import build_v3_workspace
from iac_agent.domain.plan import PlanAction, PlanSummary
from iac_agent.domain.resource import ResourceType
from iac_agent.domain.security import PolicyStatus
from iac_agent.execution.plan_analyzer import PlanAnalysisError, analyze_plan
from iac_agent.execution.terraform_runner import (
    TerraformCommandError,
    TerraformError,
    TerraformRunner,
)
from iac_agent.policies.platform import evaluate_platform_policies
from iac_agent.security.checkov import CheckovAdapter, CheckovError
from iac_agent.security.checkov_profiles import checkov_profile_for
from iac_agent.security.gate import SecurityGateError, evaluate_security_gate

_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_PERFORM = re.compile(r"perform:\s*([A-Za-z0-9-]+:[A-Za-z0-9]+)")
_SOURCE = re.compile(r'^\s*source\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
_TRUSTED_MODULE_SOURCES = frozenset(
    {
        "../../terraform/modules/sqs",
        "../../terraform/modules/s3",
        "../../terraform/modules/dynamodb",
        "../../terraform/modules/lambda",
        "../../terraform/modules/api_gateway",
        "../../terraform/modules/ecr",
    }
)
_SQS_SOURCE = "../../terraform/modules/sqs"
_PURPOSES = frozenset({"profile", "acceptance"})


def prepare(
    *,
    pr_number: int,
    proposal_sha: str,
    purpose: str,
    executor_sha: str,
    output_dir: Path,
    reader: PullRequestReader,
    show_blob: Callable[[str, str], str],
    module_source_dir: Path,
    runner: TerraformRunner | None = None,
    checkov: CheckovAdapter | None = None,
    workflow_run_id: str = "",
    workflow_run_attempt: str = "",
) -> V3Evidence | None:
    """Validate the proposal and write a handoff. Returns evidence only on failure."""
    common = _common(
        purpose=purpose,
        pr_number=pr_number,
        proposal_sha=proposal_sha,
        executor_sha=executor_sha,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
    )
    if purpose not in _PURPOSES or not _SHA.fullmatch(proposal_sha):
        return _failure(common, TerminalOutcome.CONFIGURATION_ERROR, request_id="")
    try:
        head = reader.read_pull_request(pr_number)
        request_id = bind_proposal(head, pr_number=pr_number, proposal_sha=proposal_sha)
    except ShaMismatch:
        return _failure(common, TerminalOutcome.SHA_MISMATCH, request_id="")
    except ProposalRejected:
        return _failure(common, TerminalOutcome.PROPOSAL_REJECTED, request_id="")

    try:
        main_path, versions_path = proposal_blob_paths(request_id)
        main_tf = show_blob(proposal_sha, main_path)
        versions_tf = show_blob(proposal_sha, versions_path)
    except (OSError, ValueError) as exc:
        raise ConfigurationError("proposal blobs could not be read") from exc

    sources = set(_SOURCE.findall(main_tf))
    if sources and sources <= _TRUSTED_MODULE_SOURCES and sources != {_SQS_SOURCE}:
        return _failure(common, TerminalOutcome.UNSUPPORTED, request_id=request_id)

    try:
        spec = decode_sqs_proposal(main_tf, versions_tf)
    except ProposalRejected:
        return _failure(common, TerminalOutcome.PROPOSAL_REJECTED, request_id=request_id)

    with tempfile.TemporaryDirectory() as temporary:
        built = Path(temporary) / "workspace"
        build_v3_workspace(spec, module_source_dir=module_source_dir, destination=built)
        scan = Path(temporary) / "scan"
        shutil.copytree(built, scan)
        active_runner = runner or v3_runner()
        try:
            active_runner.init(scan, env_overrides=None)
            active_runner.validate(scan, env_overrides=None)
        except TerraformError:
            return _failure(common, TerminalOutcome.TERRAFORM_ERROR, request_id=request_id)
        scanner = checkov or CheckovAdapter()
        try:
            checkov_result = scanner.scan(scan, profile=checkov_profile_for(ResourceType.SQS))
        except CheckovError:
            return _failure(common, TerminalOutcome.CONFIGURATION_ERROR, request_id=request_id)
        write_handoff(
            output_dir,
            workspace=built,
            proposal_sha=proposal_sha,
            executor_sha=executor_sha,
            pr_number=pr_number,
            repository_id=REPOSITORY_ID,
            request_id=request_id,
            proposal_main_sha256=_sha256_text(main_tf),
            proposal_versions_sha256=_sha256_text(versions_tf),
            spec=spec,
            checkov=checkov_result,
        )
    return None


def verify_handoff_command(
    *,
    handoff: Path,
    executor_sha: str,
    evidence_path: Path,
    purpose: str,
    module_source_dir: Path,
    workflow_run_id: str = "",
    workflow_run_attempt: str = "",
) -> int:
    """Verify the handoff before any AWS credential is requested.

    Success does not write a PASS evidence record. A later credential step
    can fail, and `if: always()` would otherwise upload a false pass.
    """
    from iac_agent.aws_plan.outcomes import exit_code

    try:
        verify_handoff(
            handoff,
            expected_executor_sha=executor_sha,
            module_source_dir=module_source_dir,
        )
    except HandoffRejected as exc:
        outcome = _handoff_outcome(exc)
        manifest = _manifest_or_none(handoff)
        evidence = _evidence(
            purpose=purpose,
            outcome=outcome,
            pr_number=manifest.pr_number if manifest else 0,
            proposal_sha=manifest.proposal_sha if manifest else "",
            executor_sha=executor_sha,
            request_id=manifest.request_id if manifest else "",
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=workflow_run_attempt,
            plan=_empty_plan(),
            security=_empty_security(),
            observed_account_id="",
            observed_sts_arn="",
            profile_candidate_action=None,
            terraform_version="",
            aws_provider_version="",
        )
        write_evidence(evidence_path, evidence)
        return exit_code(outcome)
    return 0


def plan_validated(
    *,
    handoff_dir: Path,
    executor_sha: str,
    module_source_dir: Path,
    evidence_path: Path,
    purpose: str,
    load_credentials: Callable[[], Mapping[str, str]],
    identity_lookup: Callable[[], tuple[str, str]],
    runner: TerraformRunner | None = None,
    workflow_run_id: str = "",
    workflow_run_attempt: str = "",
) -> V3Evidence:
    """Plan a verified handoff. Credential loading happens only after verification."""
    try:
        manifest = verify_handoff(
            handoff_dir,
            expected_executor_sha=executor_sha,
            module_source_dir=module_source_dir,
        )
    except HandoffRejected as exc:
        outcome = _handoff_outcome(exc)
        evidence = _evidence_from_manifest_failure(
            handoff_dir,
            purpose=purpose,
            outcome=outcome,
            executor_sha=executor_sha,
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=workflow_run_attempt,
        )
        write_evidence(evidence_path, evidence)
        return evidence

    if manifest.repository_id != REPOSITORY_ID:
        evidence = _from_manifest(
            manifest,
            purpose=purpose,
            outcome=TerminalOutcome.CONFIGURATION_ERROR,
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=workflow_run_attempt,
        )
        write_evidence(evidence_path, evidence)
        return evidence

    try:
        env = v3_plan_env(load_credentials())
    except ConfigurationError:
        evidence = _from_manifest(
            manifest,
            purpose=purpose,
            outcome=TerminalOutcome.CONFIGURATION_ERROR,
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=workflow_run_attempt,
        )
        write_evidence(evidence_path, evidence)
        return evidence

    observed_account = ""
    observed_arn = ""
    try:
        observed_account, observed_arn = identity_lookup()
        verify_caller_identity(account=observed_account, arn=observed_arn)
    except AccountMismatch:
        evidence = _from_manifest(
            manifest,
            purpose=purpose,
            outcome=TerminalOutcome.ACCOUNT_MISMATCH,
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=workflow_run_attempt,
            observed_account_id=observed_account,
            observed_sts_arn=observed_arn,
        )
        write_evidence(evidence_path, evidence)
        return evidence
    except Exception:
        evidence = _from_manifest(
            manifest,
            purpose=purpose,
            outcome=TerminalOutcome.AUTHENTICATION_ERROR,
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=workflow_run_attempt,
        )
        write_evidence(evidence_path, evidence)
        return evidence

    workspace = handoff_dir / "workspace"
    plan_path = workspace / "tfplan"
    active_runner = runner or v3_runner()
    evidence: V3Evidence
    try:
        try:
            active_runner.init(workspace, env_overrides=None)
            active_runner.plan(workspace, env_overrides=env)
            shown = active_runner.show_json(workspace, env_overrides=env)
        except TerraformCommandError as exc:
            text = exc.result.stderr
            if "AccessDenied" in text:
                evidence = _from_manifest(
                    manifest,
                    purpose=purpose,
                    outcome=TerminalOutcome.AUTHORIZATION_ERROR,
                    workflow_run_id=workflow_run_id,
                    workflow_run_attempt=workflow_run_attempt,
                    observed_account_id=observed_account,
                    observed_sts_arn=observed_arn,
                    profile_candidate_action=_candidate_action(text),
                )
            else:
                evidence = _from_manifest(
                    manifest,
                    purpose=purpose,
                    outcome=TerminalOutcome.TERRAFORM_ERROR,
                    workflow_run_id=workflow_run_id,
                    workflow_run_attempt=workflow_run_attempt,
                    observed_account_id=observed_account,
                    observed_sts_arn=observed_arn,
                )
        except TerraformError:
            evidence = _from_manifest(
                manifest,
                purpose=purpose,
                outcome=TerminalOutcome.TERRAFORM_ERROR,
                workflow_run_id=workflow_run_id,
                workflow_run_attempt=workflow_run_attempt,
                observed_account_id=observed_account,
                observed_sts_arn=observed_arn,
            )
        else:
            evidence = _analyze(
                manifest,
                shown=shown,
                purpose=purpose,
                workflow_run_id=workflow_run_id,
                workflow_run_attempt=workflow_run_attempt,
                observed_account_id=observed_account,
                observed_sts_arn=observed_arn,
            )
    finally:
        if plan_path.is_symlink() or plan_path.exists():
            plan_path.unlink()
    write_evidence(evidence_path, evidence)
    return evidence


def _analyze(
    manifest: HandoffManifest,
    *,
    shown: Mapping[str, object],
    purpose: str,
    workflow_run_id: str,
    workflow_run_attempt: str,
    observed_account_id: str,
    observed_sts_arn: str,
) -> V3Evidence:
    try:
        summary = analyze_plan(shown)
        platform = evaluate_platform_policies(manifest.canonical_inputs.to_spec(), summary)
        gate = evaluate_security_gate(
            platform,
            manifest.checkov.to_result(),
            resource_type=ResourceType.SQS,
        )
    except (PlanAnalysisError, SecurityGateError, HandoffRejected):
        return _from_manifest(
            manifest,
            purpose=purpose,
            outcome=TerminalOutcome.TERRAFORM_ERROR,
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=workflow_run_attempt,
            observed_account_id=observed_account_id,
            observed_sts_arn=observed_sts_arn,
        )
    outcome = (
        TerminalOutcome.PLAN_BLOCKED
        if gate.overall_status is PolicyStatus.BLOCK
        else TerminalOutcome.PASS
    )
    return _from_manifest(
        manifest,
        purpose=purpose,
        outcome=outcome,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        observed_account_id=observed_account_id,
        observed_sts_arn=observed_sts_arn,
        plan=_plan_payload(summary),
        security={
            "status": gate.overall_status.value,
            "finding_ids": [finding.policy_id for finding in gate.findings],
        },
    )


def _candidate_action(text: str) -> str | None:
    match = _PERFORM.search(text)
    if match is None:
        return None
    return match.group(1)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _common(
    *,
    purpose: str,
    pr_number: int,
    proposal_sha: str,
    executor_sha: str,
    workflow_run_id: str,
    workflow_run_attempt: str,
) -> dict[str, object]:
    return {
        "purpose": purpose,
        "pr_number": pr_number,
        "proposal_sha": proposal_sha,
        "executor_sha": executor_sha,
        "workflow_run_id": workflow_run_id,
        "workflow_run_attempt": workflow_run_attempt,
    }


def _handoff_outcome(exc: HandoffRejected) -> TerminalOutcome:
    if exc.sha_mismatch:
        return TerminalOutcome.SHA_MISMATCH
    return TerminalOutcome.CONFIGURATION_ERROR


def _failure(
    common: Mapping[str, object], outcome: TerminalOutcome, *, request_id: str
) -> V3Evidence:
    return _evidence(
        purpose=str(common["purpose"]),
        outcome=outcome,
        pr_number=int(common["pr_number"]),
        proposal_sha=str(common["proposal_sha"]),
        executor_sha=str(common["executor_sha"]),
        request_id=request_id,
        workflow_run_id=str(common["workflow_run_id"]),
        workflow_run_attempt=str(common["workflow_run_attempt"]),
        plan=_empty_plan(),
        security=_empty_security(),
        observed_account_id="",
        observed_sts_arn="",
        profile_candidate_action=None,
        terraform_version="",
        aws_provider_version="",
    )


def _from_manifest(
    manifest: HandoffManifest,
    *,
    purpose: str,
    outcome: TerminalOutcome,
    workflow_run_id: str,
    workflow_run_attempt: str,
    observed_account_id: str = "",
    observed_sts_arn: str = "",
    profile_candidate_action: str | None = None,
    plan: Mapping[str, object] | None = None,
    security: Mapping[str, object] | None = None,
) -> V3Evidence:
    return _evidence(
        purpose=purpose,
        outcome=outcome,
        pr_number=manifest.pr_number,
        proposal_sha=manifest.proposal_sha,
        executor_sha=manifest.executor_sha,
        request_id=manifest.request_id,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        plan=plan if plan is not None else _empty_plan(),
        security=security if security is not None else _empty_security(),
        observed_account_id=observed_account_id,
        observed_sts_arn=observed_sts_arn,
        profile_candidate_action=profile_candidate_action,
        terraform_version="",
        aws_provider_version="",
    )


def _evidence_from_manifest_failure(
    handoff_dir: Path,
    *,
    purpose: str,
    outcome: TerminalOutcome,
    executor_sha: str,
    workflow_run_id: str,
    workflow_run_attempt: str,
) -> V3Evidence:
    manifest = _manifest_or_none(handoff_dir)
    if manifest is None:
        return _evidence(
            purpose=purpose,
            outcome=outcome,
            pr_number=0,
            proposal_sha="",
            executor_sha=executor_sha,
            request_id="",
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=workflow_run_attempt,
            plan=_empty_plan(),
            security=_empty_security(),
            observed_account_id="",
            observed_sts_arn="",
            profile_candidate_action=None,
            terraform_version="",
            aws_provider_version="",
        )
    return _from_manifest(
        manifest,
        purpose=purpose,
        outcome=outcome,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
    )


def _manifest_or_none(handoff_dir: Path) -> HandoffManifest | None:
    try:
        from iac_agent.aws_plan.handoff import _read_manifest

        return _read_manifest(handoff_dir / "manifest.json")
    except (HandoffRejected, OSError):
        return None


def _evidence(
    *,
    purpose: str,
    outcome: TerminalOutcome,
    pr_number: int,
    proposal_sha: str,
    executor_sha: str,
    request_id: str,
    workflow_run_id: str,
    workflow_run_attempt: str,
    plan: Mapping[str, object],
    security: Mapping[str, object],
    observed_account_id: str,
    observed_sts_arn: str,
    profile_candidate_action: str | None,
    terraform_version: str,
    aws_provider_version: str,
) -> V3Evidence:
    return V3Evidence(
        schema_version="1",
        purpose=purpose,
        terminal_outcome=outcome,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        repository_id=REPOSITORY_ID,
        pr_number=pr_number,
        proposal_sha=proposal_sha,
        executor_sha=executor_sha,
        request_id=request_id,
        target={
            "account_id": AWS_ACCOUNT_ID,
            "region": AWS_REGION,
            "expected_role_arn": IAM_ROLE_ARN,
            "observed_account_id": observed_account_id,
            "observed_sts_arn": observed_sts_arn,
        },
        terraform={
            "terraform_version": terraform_version,
            "aws_provider_version": aws_provider_version,
        },
        plan=plan,
        security=security,
        profile_candidate_action=profile_candidate_action,
    )


def _empty_plan() -> dict[str, object]:
    return {"add": 0, "change": 0, "destroy": 0, "replace_addresses": [], "actions": []}


def _empty_security() -> dict[str, object]:
    return {"status": "", "finding_ids": []}


def _plan_payload(summary: PlanSummary) -> dict[str, object]:
    return {
        "add": summary.add_count,
        "change": summary.change_count,
        "destroy": summary.destroy_count,
        "replace_addresses": [
            change.address
            for change in summary.resource_changes
            if change.action is PlanAction.REPLACE
        ],
        "actions": [
            {
                "address": change.address,
                "action": change.action.value,
                "changed_fields": list(change.changed_fields),
            }
            for change in summary.resource_changes
        ],
    }

