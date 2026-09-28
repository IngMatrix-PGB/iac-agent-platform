import type { FindingDTO } from "../api/types";

export function Findings({ findings }: { findings: FindingDTO[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Policy</th>
          <th>Status</th>
          <th>Severity</th>
        </tr>
      </thead>
      <tbody>
        {findings.map((finding) => (
          <tr key={`${finding.policy_id}:${finding.status}:${finding.severity}`}>
            <td>{finding.policy_id}</td>
            <td>{finding.status}</td>
            <td>{finding.severity}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
