# Structural, single-variable rules are enforced here (mirroring the
# field-level validators in the Python SQSResourceSpec contract).
# Cross-variable consistency (fifo/name, dlq/max_receive_count) is
# enforced via lifecycle.precondition in main.tf, since Terraform
# variable validation blocks cannot reference other variables without
# requiring Terraform >= 1.9.

variable "name" {
  description = <<-EOT
    Full physical SQS queue name, including the literal ".fifo" suffix
    when fifo = true. This module does not infer, prefix, or rewrite
    the name — callers (the Terraform composer in a later batch) must
    supply the exact final name.
  EOT
  type        = string

  validation {
    condition     = length(var.name) > 0 && length(var.name) <= 80
    error_message = "name must be between 1 and 80 characters."
  }

  validation {
    condition     = can(regex("^[A-Za-z0-9_-]+(\\.fifo)?$", var.name))
    error_message = "name must contain only alphanumeric characters, hyphens, and underscores, with an optional literal '.fifo' suffix."
  }
}

variable "fifo" {
  description = "Whether this is a FIFO queue. Must be consistent with the '.fifo' suffix on name (enforced by a resource precondition)."
  type        = bool
  default     = false
}

variable "visibility_timeout_seconds" {
  description = "Visibility timeout in seconds (AWS SQS limit: 0-43200)."
  type        = number
  default     = 30

  validation {
    condition     = var.visibility_timeout_seconds >= 0 && var.visibility_timeout_seconds <= 43200
    error_message = "visibility_timeout_seconds must be between 0 and 43200."
  }
}

variable "message_retention_seconds" {
  description = "Message retention in seconds (AWS SQS limit: 60-1209600)."
  type        = number
  default     = 345600

  validation {
    condition     = var.message_retention_seconds >= 60 && var.message_retention_seconds <= 1209600
    error_message = "message_retention_seconds must be between 60 and 1209600."
  }
}

variable "delay_seconds" {
  description = "Delivery delay in seconds (AWS SQS limit: 0-900)."
  type        = number
  default     = 0

  validation {
    condition     = var.delay_seconds >= 0 && var.delay_seconds <= 900
    error_message = "delay_seconds must be between 0 and 900."
  }
}

variable "kms_key_id" {
  description = <<-EOT
    Existing KMS key ARN, key ID, or alias to use for SSE-KMS encryption.
    When null, AWS-managed SQS server-side encryption (SSE-SQS) is used
    instead. This module never provisions a KMS key and has no input
    that can disable encryption entirely.
  EOT
  type        = string
  default     = null
}

variable "dlq_enabled" {
  description = "Whether to create a dead-letter queue and wire the primary queue's redrive_policy to it."
  type        = bool
  default     = true
}

variable "max_receive_count" {
  description = <<-EOT
    Maximum receives before a message is moved to the DLQ. Must be set
    (1-1000) when dlq_enabled = true, and must be null when
    dlq_enabled = false — this module does not silently default it in
    either direction (enforced by a resource precondition).
  EOT
  type        = number
  default     = 5

  validation {
    condition     = var.max_receive_count == null || (var.max_receive_count >= 1 && var.max_receive_count <= 1000)
    error_message = "max_receive_count must be between 1 and 1000 when set."
  }
}

variable "tags" {
  description = "Tags applied to the primary queue and the DLQ, if created. Passed through as-is — no tags are injected automatically."
  type        = map(string)
  default     = {}
}
