# Structural, single-variable rules mirrored here from the Python
# LambdaResourceSpec contract's field-level validators, for defense in
# depth (same pattern already used by the trusted SQS/S3/DynamoDB
# modules). Numeric ranges and enumerated value sets verified against
# current AWS Lambda/CloudWatch Logs documentation before
# implementation (see docs/resources/lambda.md), not assumed.

variable "name" {
  description = "Lambda function name. This module does not infer, prefix, or rewrite the name."
  type        = string

  validation {
    condition     = length(var.name) >= 1 && length(var.name) <= 64
    error_message = "name must be between 1 and 64 characters."
  }

  validation {
    condition     = can(regex("^[a-zA-Z0-9_-]+$", var.name))
    error_message = "name must contain only letters, digits, underscores, and hyphens."
  }
}

variable "handler" {
  description = "The module.function entry point Lambda calls to run the function."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z_][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)+$", var.handler))
    error_message = "handler must be in the form 'module.function' (dot-separated identifiers only)."
  }
}

variable "runtime" {
  description = "Lambda runtime identifier. Phase 2 supports only python3.12."
  type        = string
  default     = "python3.12"

  validation {
    condition     = contains(["python3.12"], var.runtime)
    error_message = "runtime must be \"python3.12\" — this is the only Phase 2 supported runtime."
  }
}

variable "architecture" {
  description = "Instruction set architecture: x86_64 or arm64."
  type        = string
  default     = "arm64"

  validation {
    condition     = contains(["x86_64", "arm64"], var.architecture)
    error_message = "architecture must be one of \"x86_64\" or \"arm64\"."
  }
}

variable "memory_size_mb" {
  description = "Memory allocated to the function, in MB."
  type        = number
  default     = 256

  validation {
    condition     = var.memory_size_mb >= 128 && var.memory_size_mb <= 10240
    error_message = "memory_size_mb must be between 128 and 10240."
  }
}

variable "timeout_seconds" {
  description = "Maximum function execution time, in seconds."
  type        = number
  default     = 30

  validation {
    condition     = var.timeout_seconds >= 1 && var.timeout_seconds <= 900
    error_message = "timeout_seconds must be between 1 and 900."
  }
}

variable "reserved_concurrency" {
  description = <<-EOT
    Reserved concurrent executions. Null means no reservation is
    configured. 0 is a legitimate value (fully throttles the
    function) — this module never confuses "unset" with "zero."
  EOT
  type        = number
  default     = null

  validation {
    condition     = var.reserved_concurrency == null || var.reserved_concurrency >= 0
    error_message = "reserved_concurrency must be null or >= 0."
  }
}

variable "tracing_mode" {
  description = "AWS X-Ray tracing mode: Active or PassThrough."
  type        = string
  default     = "Active"

  validation {
    condition     = contains(["Active", "PassThrough"], var.tracing_mode)
    error_message = "tracing_mode must be one of \"Active\" or \"PassThrough\"."
  }
}

variable "log_retention_days" {
  description = <<-EOT
    CloudWatch Logs retention period, in days. Must be one of
    CloudWatch Logs' own supported values. Defaults to 365 (one year)
    — verified via a real Checkov scan of this module's secure
    baseline (CKV_AWS_338 requires at least one year of retention).
  EOT
  type        = number
  default     = 365

  validation {
    condition = contains([
      1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731,
      1096, 1827, 2192, 2557, 2922, 3288, 3653,
    ], var.log_retention_days)
    error_message = "log_retention_days must be one of CloudWatch Logs' supported retention values."
  }
}

variable "environment_variables" {
  description = "Environment variables exposed to the function. Never a secrets-management mechanism — see docs/resources/lambda.md."
  type        = map(string)
  default     = {}
}

variable "tags" {
  description = "Tags applied to the function, role, and log group. Passed through as-is — no tags are injected automatically."
  type        = map(string)
  default     = {}
}
