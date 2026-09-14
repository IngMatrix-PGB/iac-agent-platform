"""Architecture regression test: every `ResourceType` member must be
registered consistently across every dispatch/mapping surface this
platform has (Batch 18).

This exists to catch "added a new ResourceType but forgot to register
it somewhere" drift going forward, now that there are four resource
types (and presumably more later) — not to build any new abstraction.
Deliberately a small, explicit table of one representative spec per
resource type, not runtime metaprogramming: adding a fifth resource
type means adding one entry here, exactly like every other registration
touchpoint this test checks.
"""

from __future__ import annotations

from iac_agent.domain.plan import PlanAction, PlanSummary, ResourceChange
from iac_agent.domain.resource import ResourceType
from iac_agent.graph.workflow import _DEFAULT_TRUSTED_MODULE_DIRS, _RESOURCE_KIND_DISPLAY_NAMES
from iac_agent.policies.platform import (
    REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE,
    TF_NO_DESTRUCTIVE_CHANGES,
    evaluate_platform_policies,
)
from iac_agent.providers.aws.dynamodb.contract import (
    DynamoDBKeySpec,
    DynamoDBKeyType,
    DynamoDBResourceSpec,
)
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.renderer import AWSResourceRenderer
from iac_agent.providers.aws.resource import AWSResourceSpec, resource_type_of
from iac_agent.providers.aws.s3.contract import S3ResourceSpec
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
from iac_agent.security.checkov_profiles import checkov_profile_for

#: One minimal, valid representative spec per resource type — the one
#: explicit table this test needs to exercise every other registration
#: surface for every type. Extending this platform with a new resource
#: type means adding one entry here.
_EXAMPLE_SPECS: dict[ResourceType, AWSResourceSpec] = {
    ResourceType.SQS: SQSResourceSpec(name="order-events"),
    ResourceType.S3: S3ResourceSpec(name="my-example-bucket"),
    ResourceType.DYNAMODB: DynamoDBResourceSpec(
        name="orders-table", partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING)
    ),
    ResourceType.LAMBDA: LambdaResourceSpec(name="orders-processor", handler="app.handler"),
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


def test_every_resource_type_has_an_example_spec():
    """The example-spec table itself must cover every current
    `ResourceType` member — otherwise the checks below would silently
    skip whichever type is missing."""
    assert set(_EXAMPLE_SPECS) == set(ResourceType)


def test_every_resource_type_dispatches_to_itself():
    for resource_type, spec in _EXAMPLE_SPECS.items():
        assert resource_type_of(spec) is resource_type


def test_every_resource_type_has_a_renderer_dispatch_case():
    """Proves the renderer's `match` has a case for every resource
    type — not merely that construction succeeds — by dispatching a
    real spec through the real `AWSResourceRenderer` and confirming it
    produces a composition rather than falling through to the
    fail-closed `ValueError`."""
    renderer = AWSResourceRenderer()
    for spec in _EXAMPLE_SPECS.values():
        composition = renderer.render(spec, module_source="ignored-for-this-test")
        assert "main.tf" in composition.files


def test_every_resource_type_has_required_platform_policy_ids():
    for resource_type in ResourceType:
        required_ids = REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE[resource_type]
        assert required_ids
        assert TF_NO_DESTRUCTIVE_CHANGES in required_ids


def test_every_resource_type_platform_policy_evaluation_covers_its_required_ids():
    """Not just that the required-ID list exists, but that actually
    running `evaluate_platform_policies` for a real spec of each type
    produces exactly those IDs — proving the dispatch inside that
    function and the required-ID table never drift apart."""
    for resource_type, spec in _EXAMPLE_SPECS.items():
        plan_summary = _create_only_plan(f"module.example.{resource_type.value}_resource")
        evaluation = evaluate_platform_policies(spec, plan_summary)
        actual_ids = {finding.policy_id for finding in evaluation.findings}
        expected_ids = set(REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE[resource_type])
        assert actual_ids == expected_ids


def test_every_resource_type_has_a_checkov_profile():
    for resource_type in ResourceType:
        checkov_profile_for(resource_type)  # must not raise


def test_every_resource_type_has_a_trusted_module_dir_that_exists_on_disk():
    for resource_type in ResourceType:
        module_dir = _DEFAULT_TRUSTED_MODULE_DIRS[resource_type]
        assert module_dir.is_dir(), f"trusted module dir does not exist: {module_dir}"


def test_every_resource_type_has_a_non_empty_display_name():
    for resource_type in ResourceType:
        display_name = _RESOURCE_KIND_DISPLAY_NAMES[resource_type]
        assert isinstance(display_name, str)
        assert display_name.strip() == display_name
        assert display_name != ""
