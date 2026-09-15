# Trusted DynamoDB module.
#
# Security invariant: there is no variable and no code path in this
# module that can produce an unencrypted table — `server_side_encryption`
# is unconditional (mirrors the SQS/S3 modules' identical encryption
# invariant). `point_in_time_recovery` and `deletion_protection_enabled`
# are genuine caller-controlled options: disabling either is a
# legitimate (if not recommended) choice surfaced as a WARN by a later
# policy layer, not rejected here.
#
# Batch 17 scope: billing_mode is hardcoded to PAY_PER_REQUEST — there
# is no variable for it at all, so a provisioned-capacity table cannot
# be requested through this module until a future phase adds explicit
# capacity controls. Attribute blocks describe key attributes only
# (partition key, and the optional sort key) — this module never
# infers or accepts an arbitrary table-field attribute definition.
#
# No customer-managed KMS key support: `server_side_encryption.kms_key_arn`
# (verified empirically via a real `terraform plan`) requires a full KMS
# key or alias ARN and rejects the bare alias-name/key-ID forms this
# project's shared KMS validator otherwise accepts for SQS/S3 — deferred
# to a future phase rather than adding a DynamoDB-only KMS validator for
# Batch 17. This module always uses AWS-owned-key encryption.

resource "aws_dynamodb_table" "this" {
  name         = var.name
  billing_mode = "PAY_PER_REQUEST"

  hash_key  = var.hash_key_name
  range_key = var.range_key_name

  attribute {
    name = var.hash_key_name
    type = var.hash_key_type
  }

  dynamic "attribute" {
    for_each = var.range_key_name != null ? [1] : []
    content {
      name = var.range_key_name
      type = var.range_key_type
    }
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery
  }

  server_side_encryption {
    enabled = true
  }

  deletion_protection_enabled = var.deletion_protection

  tags = var.tags
}
