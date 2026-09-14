# Structural, single-variable rules mirrored here from the Python
# S3ResourceSpec contract's field-level validators, for defense in
# depth (same pattern already used by the trusted SQS module). Python
# fully owns the reserved-prefix/suffix rules (xn--, sthree-,
# amzn-s3-demo-, -s3alias, --ol-s3, .mrap, --x-s3, --table-s3) — those
# are not re-mirrored here, the same way the SQS module does not
# re-mirror every SQS contract rule either.

variable "name" {
  description = <<-EOT
    Full physical S3 bucket name. This module does not infer, prefix,
    or rewrite the name — callers supply the exact final name. Bucket
    names are globally unique across AWS; this module cannot verify
    availability, only syntax.
  EOT
  type        = string

  validation {
    condition     = length(var.name) >= 3 && length(var.name) <= 63
    error_message = "name must be between 3 and 63 characters."
  }

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]*[a-z0-9]$", var.name))
    error_message = "name must contain only lowercase letters, digits, periods, and hyphens, and must begin and end with a letter or digit."
  }

  validation {
    condition     = !can(regex("\\.\\.", var.name))
    error_message = "name must not contain two adjacent periods."
  }

  validation {
    condition     = !can(regex("^[0-9]{1,3}(\\.[0-9]{1,3}){3}$", var.name))
    error_message = "name must not be formatted as an IP address."
  }
}

variable "kms_key_id" {
  description = <<-EOT
    Existing KMS key ARN, key ID, or alias to use for SSE-KMS
    encryption. When null, AWS-managed S3 server-side encryption
    (SSE-S3 / AES256) is used instead. This module never provisions a
    KMS key and has no input that can disable encryption entirely.
  EOT
  type        = string
  default     = null
}

variable "versioning" {
  description = <<-EOT
    Whether object versioning is enabled. When false, versioning is
    explicitly suspended (existing version history, if any, is
    retained — not deleted); this module never omits the versioning
    resource entirely.
  EOT
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags applied to the bucket. Passed through as-is — no tags are injected automatically."
  type        = map(string)
  default     = {}
}
