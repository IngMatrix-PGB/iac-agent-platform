import type { FindingDTO } from "../api/types";
import { chipClass, statusLabel } from "./status-label";

export function Findings({ findings }: { findings: FindingDTO[] }) {
  return (
    <section className="panel" aria-labelledby="findings-heading">
      <h3 id="findings-heading">Security findings</h3>
      <table className="findings-table">
        <caption className="visually-hidden">Security findings</caption>
        <thead>
          <tr>
            <th scope="col">Policy</th>
            <th scope="col">Status</th>
            <th scope="col">Severity</th>
          </tr>
        </thead>
        <tbody>
          {findings.map((finding) => (
            <tr key={`${finding.policy_id}:${finding.status}:${finding.severity}`}>
              <td>
                <code className="enum">{finding.policy_id}</code>
              </td>
              <td>
                <span className={chipClass(finding.status)} title={finding.status}>
                  {statusLabel(finding.status)}
                </span>
              </td>
              <td>
                <span className="chip" title={finding.severity}>
                  {statusLabel(finding.severity)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="finding-stack">
        {findings.map((finding) => (
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
    </section>
  );
}
