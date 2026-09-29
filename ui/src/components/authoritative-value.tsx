export function enumCaption(value: string): string {
  const spaced = value.replaceAll("_", " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function AuthoritativeValue({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt role="term" aria-label={label}>
        {label}
      </dt>
      <dd>
        <span>{enumCaption(value)}</span> <code className="enum">{value}</code>
      </dd>
    </div>
  );
}
