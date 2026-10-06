import { useState } from "react";
import type { FindingDTO } from "../api/types";
import { chipClass, statusLabel } from "./status-label";

const OMITTED_WHEN_EMPTY = new Set(["pending", "running", "approved", "error"]);
const EMPTY_COPY_WHEN = new Set(["awaiting_approval", "blocked", "rejected", "pr_created"]);
const STATUS_ORDER: Record<string, number> = { block: 0, warn: 1, pass: 2 };
const SEVERITY_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
const STATUS_MARK: Record<string, string> = { block: "■", warn: "▲", pass: "●" };
// Passing checks beyond this many are collapsed behind a toggle, so a
// warning or a block is never buried among passes.
const COLLAPSE_PASSING_ABOVE = 3;

function byStatusThenSeverity(left: FindingDTO, right: FindingDTO): number {
  return (
    (STATUS_ORDER[left.status] ?? 0) - (STATUS_ORDER[right.status] ?? 0) ||
    (SEVERITY_ORDER[left.severity] ?? 9) - (SEVERITY_ORDER[right.severity] ?? 9)
  );
}

function StatusMark({ status }: { status: string }) {
  return (
    <span className={`finding-status finding-status-${status}`} title={status}>
      <span aria-hidden="true">{STATUS_MARK[status] ?? "○"} </span>
      {statusLabel(status)}
    </span>
  );
}

export function Findings({
  findings,
  workflowStatus,
  securityStatus,
}: {
  findings: FindingDTO[];
  workflowStatus?: string | null;
  securityStatus?: string | null;
}) {
  const [expanded, setExpanded] = useState(false);
  if (findings.length === 0 && workflowStatus != null && OMITTED_WHEN_EMPTY.has(workflowStatus)) {
    return null;
  }
  if (findings.length === 0 && workflowStatus != null && EMPTY_COPY_WHEN.has(workflowStatus)) {
    return <p>No findings were returned.</p>;
  }
  const ordered = [...findings].sort(byStatusThenSeverity);
  const passing = ordered.filter((finding) => finding.status === "pass");
  const collapsible = passing.length > COLLAPSE_PASSING_ABOVE;
  const shown =
    collapsible && !expanded
      ? [...ordered.filter((finding) => finding.status !== "pass"), passing[0]]
      : ordered;
  const hiddenCount = ordered.length - shown.length;

  return (
    <section className="panel findings-panel" aria-labelledby="findings-heading">
      <div className="panel-head">
        <h3 id="findings-heading">Security findings</h3>
        {securityStatus ? (
          <span className={`gate-badge gate-badge-${securityStatus}`} title={securityStatus}>
            {securityStatus.toUpperCase()}
          </span>
        ) : null}
      </div>
      <table className="findings-table">
        <caption className="visually-hidden">Security findings</caption>
        <thead className="visually-hidden">
          <tr>
            <th scope="col">Status</th>
            <th scope="col">Policy</th>
            <th scope="col">Severity</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((finding) => (
            <tr key={`${finding.policy_id}:${finding.status}:${finding.severity}`}>
              <td>
                <StatusMark status={finding.status} />
              </td>
              <td>
                <code className="enum">{finding.policy_id}</code>
              </td>
              <td>
                <span className="finding-severity" title={finding.severity}>
                  {statusLabel(finding.severity)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="finding-stack" aria-label="Security findings">
        {shown.map((finding) => (
          <li key={`${finding.policy_id}:${finding.status}:${finding.severity}`}>
            <p>Policy</p>
            <p>
              <code className="enum">{finding.policy_id}</code>
            </p>
            <p>Status</p>
            <p>
              <span className={chipClass(finding.status)} title={finding.status}>
                {statusLabel(finding.status)}
              </span>
            </p>
            <p>Severity</p>
            <p>
              <span className="chip" title={finding.severity}>
                {statusLabel(finding.severity)}
              </span>
            </p>
          </li>
        ))}
      </ul>
      {collapsible ? (
        <button
          className="findings-toggle"
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Show fewer" : `+ ${hiddenCount} more passing`}
        </button>
      ) : null}
    </section>
  );
}
