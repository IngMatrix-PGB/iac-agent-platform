# Trusted Lambda + execution-role module (Phase 2, Batch 18).
#
# This is the platform's one and only Lambda module, and it owns the
# entire multi-resource relationship internally: a Lambda function, its
# IAM execution role, one narrowly-scoped inline CloudWatch Logs
# permission policy, and the function's own log group. There is no
# separate top-level IAM resource type — the execution role is an
# implementation detail of Lambda in this phase, never independently
# requestable, never user-authored IAM JSON.
#
# Security invariants, all unconditional (no variable can disable
# them):
#   - the execution role's trust policy allows exactly one principal,
#     lambda.amazonaws.com, to assume it — never a wildcard principal;
#   - the only permissions granted are CloudWatch Logs
#     CreateLogGroup/CreateLogStream/PutLogEvents, scoped to this
#     function's own log group ARN — never "*"/"iam:*", never an
#     AWS-managed administrator policy, never permissions for any
#     other AWS resource type this platform supports (SQS/S3/
#     DynamoDB) — that is explicit Batch 19 scope, not this batch's;
#   - the log group is always explicitly created by this module (never
#     left to Lambda's own lazy, unmanaged creation) with a bounded,
#     positive retention_in_days — no indefinite-retention path exists.
#
# The deployment package is always the trusted fixture zip checked
# into this module's own directory (fixtures/placeholder.zip) — never
# a user-supplied filesystem path, never real application code. See
# docs/resources/lambda.md for why: this project only ever plans
# Terraform, never applies it, so the package's actual contents are
# irrelevant to what this batch proves; `var.handler` is metadata
# describing what a real deployment's entry point would be, decoupled
# from this fixture's actual contents.

data "aws_iam_policy_document" "assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name}-execution-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
  tags               = var.tags
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

data "aws_iam_policy_document" "logs" {
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    # Scoped to exactly this function's own log group (and its log
    # streams, via the trailing ":*") — never "*", never another
    # function's logs.
    resources = ["${aws_cloudwatch_log_group.this.arn}:*"]
  }
}

resource "aws_iam_role_policy" "logs" {
  name   = "${var.name}-logs"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.logs.json
}

resource "aws_lambda_function" "this" {
  function_name = var.name

  filename         = "${path.module}/fixtures/placeholder.zip"
  source_code_hash = filebase64sha256("${path.module}/fixtures/placeholder.zip")

  handler       = var.handler
  runtime       = var.runtime
  architectures = [var.architecture]
  role          = aws_iam_role.this.arn

  memory_size = var.memory_size_mb
  timeout     = var.timeout_seconds

  # -1 is the AWS/Terraform sentinel for "no reserved concurrency
  # configured" — never omitted silently, and never confused with the
  # legitimate 0 value (which means "fully throttle this function").
  reserved_concurrent_executions = var.reserved_concurrency == null ? -1 : var.reserved_concurrency

  tracing_config {
    mode = var.tracing_mode
  }

  environment {
    variables = var.environment_variables
  }

  tags = var.tags
}
