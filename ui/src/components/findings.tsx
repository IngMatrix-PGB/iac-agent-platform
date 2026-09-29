import type { FindingDTO } from "../api/types";

export function Findings({ findings }: { findings: FindingDTO[] }) {
  return (
    <section className="panel" aria-labelledby="findings-heading">
      <h3 id="findings-heading">Security findings</h3>
      <table>
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
                <code className="enum">{finding.status}</code>
              </td>
              <td>
                <code className="enum">{finding.severity}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
