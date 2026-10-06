import type { WorkflowDTO } from "../api/types";

type StepState = "done" | "current" | "warn" | "stopped" | "todo";

const STEPS = ["intent", "resolve", "render", "plan", "policy", "gate", "human", "pr"] as const;

const GATE = STEPS.indexOf("gate");
const HUMAN = STEPS.indexOf("human");
const PR = STEPS.indexOf("pr");

const STAGE_INDEX: Record<string, number> = {
  render: 2,
  terraform: 3,
  plan_analysis: 3,
  platform_policy: 4,
  checkov: 4,
  security_gate: GATE,
  approval: HUMAN,
  source_control: PR,
};

const STATE_WORDS: Record<StepState, string> = {
  done: "done",
  current: "in progress",
  warn: "passed with warnings",
  stopped: "stopped",
  todo: "not reached",
};

function stepStates(workflow: WorkflowDTO): StepState[] {
  const status = workflow.workflow_status;
  const reached = (current: number, at: StepState): StepState[] =>
    STEPS.map((_, index) => (index < current ? "done" : index === current ? at : "todo"));

  let states: StepState[];
  if (status === "pr_created") {
    states = STEPS.map(() => "done");
  } else if (status === "approved") {
    states = reached(PR, "current");
  } else if (status === "awaiting_approval") {
    states = reached(HUMAN, "current");
  } else if (status === "rejected") {
    states = reached(HUMAN, "stopped");
  } else if (status === "blocked") {
    states = reached(GATE, "stopped");
  } else if (status === "error") {
    const stage = workflow.error?.stage ?? workflow.current_stage ?? "render";
    states = reached(STAGE_INDEX[stage] ?? STAGE_INDEX.render, "stopped");
  } else {
    states = reached(STAGE_INDEX[workflow.current_stage ?? "render"] ?? STAGE_INDEX.render, "current");
  }

  if (workflow.security_status === "warn" && states[GATE] === "done") {
    states[GATE] = "warn";
  }
  return states;
}

export function Pipeline({ workflow }: { workflow: WorkflowDTO | null }) {
  if (!workflow) {
    return null;
  }
  const states = stepStates(workflow);
  return (
    <ol className="pipeline" aria-label="Workflow pipeline">
      {STEPS.map((step, index) => (
        <li
          key={step}
          data-state={states[index]}
          aria-current={states[index] === "current" ? "step" : undefined}
        >
          {step}
          <span className="visually-hidden">: {STATE_WORDS[states[index]]}</span>
        </li>
      ))}
    </ol>
  );
}
