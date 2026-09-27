"""Unit tests for `CompositionType` itself (Batch 26).

Cross-cutting registration (every dispatch surface recognizing the new
member) is proven separately by
`tests/unit/test_composition_registration_consistency.py` — this file
only proves the enum's own shape.
"""

from __future__ import annotations

from iac_agent.domain.composition import CompositionType


def test_composition_type_has_exactly_three_members():
    assert len(CompositionType) == 3


def test_api_gateway_lambda_dynamodb_member_value():
    assert CompositionType.API_GATEWAY_LAMBDA_DYNAMODB.value == "api_gateway_lambda_dynamodb"
