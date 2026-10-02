import { useState, type FormEvent } from "react";

export function OpenRequest({ navigate }: { navigate: (path: string) => void }) {
  const [requestId, setRequestId] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = requestId.trim();
    if (!trimmed) {
      return;
    }
    navigate(`/requests/${encodeURIComponent(trimmed)}`);
  }

  return (
    <form className="panel" onSubmit={submit}>
      <label htmlFor="open-request-id">Request id</label>
      <input
        id="open-request-id"
        value={requestId}
        onChange={(event) => setRequestId(event.target.value)}
      />
      <button className="button-secondary" type="submit">Open request</button>
    </form>
  );
}
