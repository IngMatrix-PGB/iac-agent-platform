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
      <h3 id="approval-heading">Approval decision</h3>
      <p>Reject sends immediately and does not ask for confirmation.</p>
      <button ref={approveRef} type="button" disabled={busy} onClick={() => setOpen(true)}>
        Approve
      </button>
      <button type="button" disabled={busy} onClick={() => void decide("reject")}>
        Reject request
      </button>
      {open ? (
        <dialog ref={dialogRef} aria-labelledby="approve-confirm-title">
          <p id="approve-confirm-title">{CONFIRM_TEXT}</p>
          <button type="button" data-dialog-initial-focus disabled={busy} onClick={cancel}>
            Cancel
          </button>
          <button type="button" disabled={busy} onClick={() => void decide("approve")}>
            Confirm approval
          </button>
        </dialog>
      ) : null}
    </section>
  );
}
