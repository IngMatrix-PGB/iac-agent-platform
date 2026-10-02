const LABELS: Record<string, string> = {
  pass: "Pass",
  warn: "Warn",
  block: "Block",
  awaiting_approval: "Awaiting approval",
  pending: "Pending",
  running: "Running",
  approved: "Approved",
  rejected: "Rejected",
  blocked: "Blocked",
  error: "Error",
  pr_created: "Pull request created",
  render: "Render",
  terraform: "Terraform",
  terraform_plan: "Terraform plan",
  plan_analysis: "Plan analysis",
  platform_policy: "Platform policy",
  checkov: "Checkov",
  security_gate: "Security gate",
  approval: "Approval",
  source_control: "Source control",
  complete: "Complete",
  publish: "Publish",
  high: "High",
  medium: "Medium",
  low: "Low",
  critical: "Critical",
};

const CHIP: Record<string, string> = {
  pass: "chip chip-pass",
  warn: "chip chip-warn",
  block: "chip chip-block",
  blocked: "chip chip-block",
  awaiting_approval: "chip chip-attention",
  pr_created: "chip chip-published",
  pending: "chip chip-neutral",
  running: "chip chip-neutral",
  approved: "chip chip-neutral",
  rejected: "chip chip-rejected",
  error: "chip chip-error",
};

export function enumCaption(value: string): string {
  const spaced = value.replaceAll("_", " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function statusLabel(value: string): string {
  return LABELS[value] ?? enumCaption(value);
}

export function chipClass(value: string): string {
  return CHIP[value] ?? "chip";
}
