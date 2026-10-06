import { useEffect, useRef, useState } from "react";
import type { ApiClient, ClientResult } from "../api/client";
import type { RequestResponse } from "../api/types";

const CONFIRM_TEXT =
  "Approval resumes the workflow and publication may create a pull request. Terraform apply will not run.";

export function ApprovalPanel({
  body,
  client,
  onResult,
}: {
  body: RequestResponse;
  client: ApiClient;
  onResult: (result: ClientResult) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const approveRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }
    const dialog = dialogRef.current;
    if (!dialog) {
      return;
    }
    if (typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
    dialog.querySelector<HTMLButtonElement>("[data-dialog-initial-focus]")?.focus();
  }, [open]);

  if (!body.approval_available) {
    return null;
  }

  async function decide(decision: "approve" | "reject") {
    setBusy(true);
    const result = await client.decide(body.request_id, decision);
    setBusy(false);
    setOpen(false);
    onResult(result);
  }

  function cancel() {
    setOpen(false);
    approveRef.current?.focus();
  }

  return (
    <section className="panel decision" aria-labelledby="approval-heading" aria-busy={busy}>
      <div className="decision-row">
      <div className="decision-head">
        <svg
          className="decision-lock"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <rect x="5" y="11" width="14" height="10" rx="2" />
          <path d="M8 11V7a4 4 0 0 1 8 0v4" />
        </svg>
        <div>
          <h3 id="approval-heading">Human authorization</h3>
          <p className="decision-note">
            Approving opens a pull request. Terraform apply does not run.
          </p>
        </div>
      </div>
      <div className="approval-actions">
        <button
          className="button-secondary"
          type="button"
          disabled={busy}
          aria-label="Reject request"
          onClick={() => void decide("reject")}
        >
          Reject
        </button>
        <button
          ref={approveRef}
          className="button-primary"
          type="button"
          disabled={busy}
          onClick={() => setOpen(true)}
        >
          Approve
        </button>
      </div>
      </div>
      <p className="decision-reject-note">Reject sends immediately and does not ask for confirmation.</p>
      {open ? (
        <dialog ref={dialogRef} aria-labelledby="approve-confirm-title">
          <p id="approve-confirm-title">{CONFIRM_TEXT}</p>
          <button
            className="button-secondary"
            type="button"
            data-dialog-initial-focus
            disabled={busy}
            onClick={cancel}
          >
            Cancel
          </button>
          <button
            className="button-primary"
            type="button"
            disabled={busy}
            onClick={() => void decide("approve")}
          >
            Confirm approval
          </button>
        </dialog>
      ) : null}
    </section>
  );
}
