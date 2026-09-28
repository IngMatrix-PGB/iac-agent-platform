import { useEffect, useRef } from "react";

export function ErrorBanner({ message }: { message: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
  }, [message]);
  return (
    <div className="banner" role="alert" tabIndex={-1} ref={ref}>
      {message}
    </div>
  );
}
