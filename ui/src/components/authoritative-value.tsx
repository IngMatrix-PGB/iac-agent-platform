import { chipClass, statusLabel } from "./status-label";

export { enumCaption, statusLabel } from "./status-label";

export function AuthoritativeValue({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt role="term" aria-label={label}>
        {label}
      </dt>
      <dd>
        <span className={chipClass(value)} title={value}>
          {statusLabel(value)}
        </span>
      </dd>
    </div>
  );
}
