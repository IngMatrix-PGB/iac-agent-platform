import type { FormEvent } from "react";

export function RequestForm({
  value,
  busy,
  onChange,
  onSubmit,
}: {
  value: string;
  busy: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
}) {
  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <form className="panel" aria-busy={busy} onSubmit={submit}>
      <label htmlFor="infrastructure-request">Infrastructure request</label>
      <textarea
        id="infrastructure-request"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      <button className="button-primary" type="submit" disabled={busy}>
        Submit request
      </button>
    </form>
  );
}
