# Trusted SQS module.
#
# Security invariant: there is no variable and no code path in this
# module that can produce an unencrypted queue. Encryption is always
# one of SSE-SQS (AWS-managed key, the default) or SSE-KMS (an
# existing, caller-supplied key). This module never creates a KMS key.

locals {
  use_kms = var.kms_key_id != null
}

resource "aws_sqs_queue" "dlq" {
  count = var.dlq_enabled ? 1 : 0

  name       = var.fifo ? "${trimsuffix(var.name, ".fifo")}-dlq.fifo" : "${var.name}-dlq"
  fifo_queue = var.fifo

  sqs_managed_sse_enabled = local.use_kms ? null : true
  kms_master_key_id       = local.use_kms ? var.kms_key_id : null

  tags = var.tags
}

resource "aws_sqs_queue" "this" {
  name       = var.name
  fifo_queue = var.fifo

  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_seconds
  delay_seconds              = var.delay_seconds

  sqs_managed_sse_enabled = local.use_kms ? null : true
  kms_master_key_id       = local.use_kms ? var.kms_key_id : null

  redrive_policy = var.dlq_enabled ? jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[0].arn
    maxReceiveCount     = var.max_receive_count
  }) : null

  tags = var.tags

  lifecycle {
    precondition {
      condition     = var.fifo == endswith(var.name, ".fifo")
      error_message = "fifo must be true if and only if name ends with '.fifo'. This module does not rewrite the name to match — the caller must supply a consistent (fifo, name) pair."
    }

    precondition {
      condition     = var.dlq_enabled ? var.max_receive_count != null : var.max_receive_count == null
      error_message = "max_receive_count must be set when dlq_enabled is true, and null when dlq_enabled is false."
    }
  }
}
