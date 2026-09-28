export interface FindingDTO {
  policy_id: string;
  status: string;
  severity: string;
}

export interface PlanDTO {
  add: number;
  change: number;
  destroy: number;
  destructive_change_detected: boolean;
}

export interface ComponentDTO {
  role: string;
  name: string;
  image_tag_mutability?: string | null;
  scan_on_push?: boolean | null;
}

export interface IntentDTO {
  workload_type: string;
  interaction_pattern: string;
  capabilities: string[];
}

export interface ResolutionDTO {
  outcome: string;
  matched_pattern?: string | null;
  architecture?: string | null;
  name?: string | null;
  components?: ComponentDTO[];
  field?: string | null;
  reason?: string | null;
  allowed_values?: string[] | null;
  detail?: string | null;
}

export interface WorkflowErrorDTO {
  stage: string;
  error_type: string;
}

export interface PullRequestDTO {
  url: string;
}

export interface WorkflowDTO {
  workflow_status: string;
  current_stage?: string | null;
  security_status?: string | null;
  plan?: PlanDTO | null;
  findings: FindingDTO[];
  approval_decision?: string | null;
  error?: WorkflowErrorDTO | null;
  pull_request?: PullRequestDTO | null;
}

export interface RequestResponse {
  request_id: string;
  outcome: string;
  approval_available: boolean;
  terraform_apply: "not_executed";
  intent: IntentDTO | null;
  resolution: ResolutionDTO;
  workflow: WorkflowDTO | null;
}

export interface ApiErrorBody {
  error: string;
  message: string;
  request_id?: string;
  request?: RequestResponse;
}
