# GENERATED FILE — do not edit by hand.
# Produced deterministically by ApiLambdaDynamoDbTerraformRenderer from a
# validated ApiLambdaDynamoDbSpec. Regenerate instead of modifying.

provider "aws" {
  region = "us-east-1"

  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
}

module "api" {
  source = "../../../../../opt/iac-agent/terraform/modules/api_gateway"

  name        = "customer-orders-api-api"
  description = null
  tags        = {}
}

module "function" {
  source = "../../../../../opt/iac-agent/terraform/modules/lambda"

  name                  = "customer-orders-api-function"
  handler               = "app.handler"
  runtime               = "python3.12"
  architecture          = "arm64"
  memory_size_mb        = 256
  timeout_seconds       = 30
  reserved_concurrency  = null
  tracing_mode          = "Active"
  log_retention_days    = 365
  environment_variables = {}
  tags                  = {}
}

module "table" {
  source = "../../../../../opt/iac-agent/terraform/modules/dynamodb"

  name                   = "customer-orders-api-table"
  hash_key_name          = "id"
  hash_key_type          = "S"
  range_key_name         = null
  range_key_type         = null
  point_in_time_recovery = true
  deletion_protection    = true
  tags                   = {}
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = module.api.api_id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = module.function.function_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "this" {
  api_id    = module.api.api_id
  route_key = "POST /invoke"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "customer-orders-api-apigateway-invoke"
  action        = "lambda:InvokeFunction"
  function_name = module.function.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api.execution_arn}/$default/POST/invoke"
}

data "aws_iam_policy_document" "dynamodb_write" {
  statement {
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
    ]
    resources = [module.table.table_arn]
  }
}

resource "aws_iam_role_policy" "dynamodb_write" {
  name   = "customer-orders-api-dynamodb-write"
  role   = module.function.execution_role_name
  policy = data.aws_iam_policy_document.dynamodb_write.json
}
