# Structural, single-variable rules mirrored here from the Python
# DynamoDBResourceSpec contract's field-level validators, for defense
# in depth (same pattern already used by the trusted SQS/S3 modules).
# Verified against the current AWS DynamoDB naming-rules documentation
# before implementation (see docs/resources/dynamodb.md), not assumed
# from an older ruleset.

variable "name" {
  description = <<-EOT
    DynamoDB table name. This module does not infer, prefix, or
    rewrite the name — callers supply the exact final name.
  EOT
  type        = string

  validation {
    condition     = length(var.name) >= 3 && length(var.name) <= 255
    error_message = "name must be between 3 and 255 characters."
  }

  validation {
    condition     = can(regex("^[a-zA-Z0-9_.-]+$", var.name))
    error_message = "name must contain only letters, digits, underscores, hyphens, and periods."
  }
}

variable "hash_key_name" {
  description = "Partition (hash) key attribute name."
  type        = string

  validation {
    condition     = length(var.hash_key_name) > 0
    error_message = "hash_key_name must not be empty."
  }
}

variable "hash_key_type" {
  description = "Partition (hash) key attribute type: S (string), N (number), or B (binary)."
  type        = string

  validation {
    condition     = contains(["S", "N", "B"], var.hash_key_type)
    error_message = "hash_key_type must be one of \"S\", \"N\", or \"B\"."
  }
}

variable "range_key_name" {
  description = "Optional sort (range) key attribute name. Null means no sort key."
  type        = string
  default     = null

  validation {
    condition     = var.range_key_name == null || length(var.range_key_name) > 0
    error_message = "range_key_name must not be an empty string — use null to omit a sort key."
  }
}

variable "range_key_type" {
  description = "Sort (range) key attribute type: S, N, or B. Required only when range_key_name is set."
  type        = string
  default     = null

  validation {
    condition     = var.range_key_type == null || contains(["S", "N", "B"], var.range_key_type)
    error_message = "range_key_type must be one of \"S\", \"N\", or \"B\" when set."
  }
}

variable "point_in_time_recovery" {
  description = "Whether point-in-time recovery is enabled."
  type        = bool
  default     = true
}

variable "deletion_protection" {
  description = "Whether table deletion protection is enabled."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags applied to the table. Passed through as-is — no tags are injected automatically."
  type        = map(string)
  default     = {}
}
