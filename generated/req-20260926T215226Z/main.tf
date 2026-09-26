# GENERATED FILE — do not edit by hand.
# Produced deterministically by ServerlessWorkerTerraformRenderer from a
# validated ServerlessWorkerSpec. Regenerate instead of modifying.

provider "aws" {
  region = "us-east-1"

  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
}

module "queue" {
  source = "../../terraform/modules/sqs"

  name                       = "queue-processor-queue"
  fifo                       = false
  visibility_timeout_seconds = 30
  message_retention_seconds  = 345600
  delay_seconds              = 0
  kms_key_id                 = null
  dlq_enabled                = true
  max_receive_count          = 5
  tags                       = {}
}

module "table" {
  source = "../../terraform/modules/dynamodb"

  name                   = "queue-processor-table"
  hash_key_name          = "id"
  hash_key_type          = "S"
  range_key_name         = null
  range_key_type         = null
  point_in_time_recovery = true
  deletion_protection    = true
  tags                   = {}
}

module "function" {
  source = "../../terraform/modules/lambda"

  name                 = "queue-processor-function"
  handler              = "app.handler"
  runtime              = "python3.12"
  architecture         = "arm64"
  memory_size_mb       = 256
  timeout_seconds      = 30
  reserved_concurrency = null
  tracing_mode         = "Active"
  log_retention_days   = 365
  environment_variables = merge(
    {},
    {
      QUEUE_URL  = module.queue.queue_url
      TABLE_NAME = module.table.table_name
    }
  )
  tags = {}
}

resource "aws_lambda_event_source_mapping" "queue_to_function" {
  event_source_arn = module.queue.queue_arn
  function_name    = module.function.function_name
  batch_size       = 10
  enabled          = true
}

data "aws_iam_policy_document" "sqs_consumer" {
  statement {
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
    ]
    resources = [module.queue.queue_arn]
  }
}

resource "aws_iam_role_policy" "sqs_consumer" {
  name   = "queue-processor-sqs-consumer"
  role   = module.function.execution_role_name
  policy = data.aws_iam_policy_document.sqs_consumer.json
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
  name   = "queue-processor-dynamodb-write"
  role   = module.function.execution_role_name
  policy = data.aws_iam_policy_document.dynamodb_write.json
}
