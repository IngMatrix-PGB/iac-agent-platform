"""Architecture regression test: every `CompositionType` member must be
registered consistently across every dispatch/mapping surface this
platform has (Batch 20).

Mirrors `tests/unit/test_resource_registration_consistency.py` exactly
in structure and intent, now for compositions: a small, explicit table
of one representative spec per composition type, not runtime
metaprogramming. Adding a third composition means adding one entry
here, exactly like every other registration touchpoint this test
checks.
"""

from __future__ import annotations

from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec, HttpMethod, RouteSpec
from iac_agent.compositions.resource import CompositionSpec, composition_type_of
from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.domain.composition import CompositionType
from iac_agent.domain.plan import PlanAction, PlanSummary, ResourceChange
from iac_agent.domain.resource import ResourceType
from iac_agent.graph.workflow import _DEFAULT_TRUSTED_MODULE_DIRS
from iac_agent.persistence.checkpoints import _ALLOWED_WORKFLOW_TYPES
from iac_agent.policies.composition import (
    REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE,
    evaluate_composition_policies,
)
from iac_agent.policies.shared import TF_NO_DESTRUCTIVE_CHANGES
from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.dynamodb.contract import DynamoDBKeySpec, DynamoDBResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
from iac_agent.request import IacRenderer
from iac_agent.security.composition_checkov_profiles import composition_checkov_profile_for

#: One minimal, valid representative spec per composition type — the
#: one explicit table this test needs to exercise every other
#: registration surface for every type.
_EXAMPLE_SPECS: dict[CompositionType, CompositionSpec] = {
    CompositionType.SQS_LAMBDA_DYNAMODB: ServerlessWorkerSpec(
        name="orders-worker",
        queue=SQSResourceSpec(name="orders-queue"),
        function=LambdaResourceSpec(
            name="orders-processor", handler="app.handler", reserved_concurrency=5
        ),
        table=DynamoDBResourceSpec(
            name="orders-table", partition_key=DynamoDBKeySpec(name="pk", type="S")
        ),
    ),
    CompositionType.API_GATEWAY_LAMBDA: ApiLambdaSpec(
        name="orders-api-worker",
        api=ApiGatewayResourceSpec(name="orders-api"),
        function=LambdaResourceSpec(
            name="orders-handler", handler="app.handler", reserved_concurrency=5
        ),
        route=RouteSpec(method=HttpMethod.POST, path="/orders"),
    ),
}

#: Every trusted-module resource type each composition's constituent
#: sub-resources need registered under `ResourceType` — used to prove
#: `_DEFAULT_TRUSTED_MODULE_DIRS` covers what each composition actually
#: needs, without inventing a second `CompositionType`-keyed mapping.
_CONSTITUENT_RESOURCE_TYPES: dict[CompositionType, tuple[ResourceType, ...]] = {
    CompositionType.SQS_LAMBDA_DYNAMODB: (
        ResourceType.SQS,
        ResourceType.LAMBDA,
        ResourceType.DYNAMODB,
    ),
    CompositionType.API_GATEWAY_LAMBDA: (ResourceType.API_GATEWAY, ResourceType.LAMBDA),
}


def _create_only_plan(address: str) -> PlanSummary:
    change = ResourceChange(
        address=address,
        actions=("create",),
        action=PlanAction.CREATE,
        replacement=False,
        destructive=False,
    )
    return PlanSummary(
        resource_changes=(change,),
        resources_to_add=(address,),
        resources_to_change=(),
        resources_to_destroy=(),
        destructive_change_detected=False,
    )


def test_every_composition_type_has_an_example_spec():
    """The example-spec table itself must cover every current
    `CompositionType` member — otherwise the checks below would
    silently skip whichever type is missing."""
    assert set(_EXAMPLE_SPECS) == set(CompositionType)


def test_every_composition_type_dispatches_to_itself():
    for composition_type, spec in _EXAMPLE_SPECS.items():
        assert composition_type_of(spec) is composition_type


def test_every_composition_type_has_a_request_level_renderer_dispatch_case():
    """Proves `IacRenderer`'s `match` has a case for every composition
    type — not merely that construction succeeds — by dispatching a
    real spec through the real `IacRenderer` and confirming it produces
    a composition rather than falling through to the fail-closed
    `ValueError`."""
    renderer = IacRenderer()
    for composition_type, spec in _EXAMPLE_SPECS.items():
        module_source_dirs = {
            resource_type: _DEFAULT_TRUSTED_MODULE_DIRS[resource_type]
            for resource_type in _CONSTITUENT_RESOURCE_TYPES[composition_type]
        }
        composition = renderer.render(
            spec,
            trusted_module_dirs=module_source_dirs,
            workspace=_DEFAULT_TRUSTED_MODULE_DIRS[ResourceType.SQS].parent.parent / "artifacts",
        )
        assert "main.tf" in composition.files


def test_every_composition_type_has_required_policy_ids():
    for composition_type in CompositionType:
        required_ids = REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE[composition_type]
        assert required_ids
        assert TF_NO_DESTRUCTIVE_CHANGES in required_ids


def test_every_composition_type_policy_evaluation_covers_its_required_ids():
    """Not just that the required-ID list exists, but that actually
    running `evaluate_composition_policies` for a real spec of each
    type produces exactly those IDs — proving the dispatch inside that
    function and the required-ID table never drift apart."""
    for composition_type, spec in _EXAMPLE_SPECS.items():
        plan_summary = _create_only_plan(f"module.example.{composition_type.value}_resource")
        evaluation = evaluate_composition_policies(spec, plan_summary)
        actual_ids = {finding.policy_id for finding in evaluation.findings}
        expected_ids = set(REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE[composition_type])
        assert actual_ids == expected_ids


def test_every_composition_type_has_a_checkov_profile():
    for composition_type in CompositionType:
        composition_checkov_profile_for(composition_type)  # must not raise


def test_every_composition_types_constituent_resource_types_have_trusted_module_dirs():
    """A composition needs no separate `CompositionType`-keyed trusted-
    module-directory mapping — but every `ResourceType` it is built
    from must already be registered in
    `_DEFAULT_TRUSTED_MODULE_DIRS`, and that directory must exist."""
    for composition_type in CompositionType:
        for resource_type in _CONSTITUENT_RESOURCE_TYPES[composition_type]:
            module_dir = _DEFAULT_TRUSTED_MODULE_DIRS[resource_type]
            assert module_dir.is_dir(), f"trusted module dir does not exist: {module_dir}"


def test_every_composition_spec_type_is_registered_for_persistence():
    """Every composition spec class (and its nested enum/model types)
    must appear in the checkpoint serializer's allowlist — otherwise a
    durable interrupt could never round-trip through SQLite for that
    composition type."""
    allowed_type_names = {qualname for _module, qualname in _ALLOWED_WORKFLOW_TYPES}
    for spec in _EXAMPLE_SPECS.values():
        assert type(spec).__name__ in allowed_type_names, (
            f"{type(spec).__name__} is missing from _ALLOWED_WORKFLOW_TYPES"
        )
