import type { PlanDTO } from "../api/types";

export function PlanSummary({ plan }: { plan: PlanDTO | null }) {
  if (!plan) {
    return <p>No plan summary was returned.</p>;
  }
  const destructive = plan.destructive_change_detected;
  return (
    <section
      className={destructive ? "panel panel-destructive" : "panel"}
      aria-labelledby="plan-summary-heading"
    >
      <h3 id="plan-summary-heading">Terraform plan summary</h3>
      <dl className="plan-counts">
        <div>
          <dt role="term" aria-label="Add" className="visually-hidden">
            Add
          </dt>
          <dd className="plan-add">{plan.add}</dd>
        </div>
        <div>
          <dt role="term" aria-label="Change" className="visually-hidden">
            Change
          </dt>
          <dd className="plan-change">{plan.change}</dd>
        </div>
        <div>
          <dt role="term" aria-label="Destroy" className="visually-hidden">
            Destroy
          </dt>
          <dd className="plan-destroy">{plan.destroy}</dd>
        </div>
      </dl>
      {destructive ? (
        <p className="destructive-sentence">Destructive change detected.</p>
      ) : (
        <p className="plan-note">No destructive changes</p>
      )}
    </section>
  );
}
