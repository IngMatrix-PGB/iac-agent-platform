variable "aws_region" {
  type        = string
  description = "AWS region the bootstrap provider connects to — the control plane's own region choice, independent of any workload region."
}

variable "github_oidc_subject" {
  type        = string
  description = <<-EOT
    The exact GitHub OIDC 'sub' claim this role trusts (design spec
    §5). Never hardcode this — always the value confirmed by the
    claim-discovery runbook (docs/aws-plan-boundary.md) for this
    specific repository, since the legacy vs. immutable subject format
    depends on this repository's own creation date and settings.
  EOT
}

variable "github_oidc_thumbprints" {
  type        = list(string)
  description = <<-EOT
    GitHub Actions OIDC provider thumbprint(s) — verify current
    AWS/GitHub guidance at apply time (design spec §6); do not assume
    this module's authoring-date values remain correct.
  EOT
}

variable "iac_plan_role_name" {
  type        = string
  default     = "IaCPlanRole"
  description = "Name of the least-privilege role GitHub Actions assumes for real AWS Terraform plans."
}

variable "max_session_duration_seconds" {
  type        = number
  default     = 3600
  description = <<-EOT
    AWS enforces a hard minimum of 3600 seconds for an IAM role's own
    max_session_duration (range 3600-43200) — this is the role-level
    CEILING, not the actual session length. The real, short-lived
    per-run duration (design spec §6) is requested independently, at
    AssumeRoleWithWebIdentity time, via the CI job's own
    role-duration-seconds input (implementation plan Task 13) — which
    can be any value at or below this ceiling, e.g. 900s.
  EOT
}
