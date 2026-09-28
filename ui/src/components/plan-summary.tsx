import type { PlanDTO } from "../api/types";

export function PlanSummary({ plan }: { plan: PlanDTO | null }) {
  if (!plan) {
    return <p>No plan summary was returned.</p>;
  }
  return (
    <section>
      <p>Add</p>
      <p>{plan.add}</p>
      <p>Change</p>
      <p>{plan.change}</p>
      <p>Destroy</p>
      <p>{plan.destroy}</p>
      {plan.destructive_change_detected ? <p>Destructive change detected.</p> : null}
    </section>
  );
}
