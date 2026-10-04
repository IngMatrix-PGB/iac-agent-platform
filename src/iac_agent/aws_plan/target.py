"""Fixed V3 target. These values are not workflow inputs and not model output."""

from __future__ import annotations

AWS_ACCOUNT_ID = "891377250201"
AWS_REGION = "us-east-1"
ROLE_NAME = "IaCPlanRole"
IAM_ROLE_ARN = "arn:aws:iam::891377250201:role/IaCPlanRole"
REPOSITORY_ID = "1368782253"
REPOSITORY_FULL_NAME = "IngMatrix-PGB/iac-agent-platform"
EXPECTED_OIDC_SUBJECT = (
    "repo:IngMatrix-PGB@167713460/iac-agent-platform@1368782253:environment:aws-plan"
)
HANDOFF_MAX_BYTES = 1_048_576
V3_PLAN_TIMEOUT_SECONDS = 300.0
