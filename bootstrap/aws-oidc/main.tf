# Bootstrap Terraform — IaCPlanRole trusted to the account's existing
# GitHub Actions OIDC provider. This module does not create that provider.
#
# This module is NEVER applied by iac-agent-platform. It is human-
# applied reference source only — see README.md in this directory.
# iac-agent-platform's own TerraformRunner/build_iac_workflow never
# references this directory as a trusted module (proven by
# tests/unit/bootstrap/test_no_self_management.py).

provider "aws" {
  region = var.aws_region
}

data "aws_iam_policy_document" "github_actions_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [var.github_oidc_subject]
    }
  }
}

data "aws_iam_openid_connect_provider" "github_actions" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_role" "iac_plan_role" {
  name                 = var.iac_plan_role_name
  assume_role_policy   = data.aws_iam_policy_document.github_actions_assume_role.json
  max_session_duration = var.max_session_duration_seconds
}

resource "aws_iam_role_policy" "iac_plan_role_permissions" {
  name   = "${var.iac_plan_role_name}-permissions"
  role   = aws_iam_role.iac_plan_role.id
  policy = file("${path.module}/policy/iac_plan_role_permissions.json")
}
