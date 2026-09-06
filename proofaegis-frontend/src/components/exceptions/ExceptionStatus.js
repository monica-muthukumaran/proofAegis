import { html, useState } from "../../lib.js";
import * as api from "../../services/api.js";
import { useAuth } from "../../services/AuthContext.js";
import { Badge } from "../ui/primitives.js";

// Only user-settable statuses appear here — system-set statuses (received,
// processing, exception_detected, assigned) are pipeline-only, same rule
// the backend enforces server-side in routes/exceptions.py.
const USER_SETTABLE = [
  "awaiting_procurement", "awaiting_receiving", "awaiting_vendor",
  "approved_with_exception", "resolved", "closed",
];

const TONE = {
  awaiting_procurement: "warning", awaiting_receiving: "warning", awaiting_vendor: "accent",
  approved_with_exception: "verified", resolved: "verified", closed: "neutral",
  exception_detected: "exception", assigned: "warning", processing: "neutral", received: "neutral",
};

export function ExceptionStatus({ exceptionId, status, onChanged }) {
  const { user } = useAuth();
  const [updating, setUpdating] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState(null);

  const handleChange = async (e) => {
    const newStatus = e.target.value;
    if (!newStatus) return;
    setUpdating(true);
    setError(null);
    const r = await api.updateStatus(exceptionId, newStatus, user ? user.email : "unknown", note || undefined);
    setUpdating(false);
    if (r.source === "error") { setError(r.error || "That status cannot be set directly."); return; }
    setNote("");
    onChanged && onChanged(r.data);
  };

  return html`
    <div class="stack gap-8">
      <div class="row gap-12" style=${{ flexWrap: "wrap" }}>
        <${Badge} tone=${TONE[status] || "neutral"}>Current: ${status.replaceAll("_", " ")}<//>
        <select class="input" style=${{ maxWidth: 240 }} aria-label="Set exception status" onChange=${handleChange} disabled=${updating} value="">
          <option value="" disabled>Set status…</option>
          ${USER_SETTABLE.map((s) => html`<option key=${s} value=${s}>${s.replaceAll("_", " ")}</option>`)}
        </select>
      </div>
      <input class="input" aria-label="Optional audit note" placeholder="Optional note for the audit trail" value=${note} onInput=${(e) => setNote(e.target.value)} style=${{ maxWidth: 420 }} />
      ${error ? html`<span class="form-feedback form-feedback-error text-small" role="alert">${error}</span>` : null}
      <p class="text-muted text-small">Status changes are made by a human reviewer and recorded in the audit trail. ProofAegis never changes status automatically.</p>
    </div>
  `;
}
