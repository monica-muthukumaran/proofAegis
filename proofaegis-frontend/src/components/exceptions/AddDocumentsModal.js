// AddDocumentsModal.js — adds documents to a case that already exists.
//
// The counterpart to CreateExceptionModal, and the reason a case is never
// "full": evidence arrives late in real AP work. A goods receipt that turns
// up two days after the invoice should turn a missing-receipt finding into a
// real quantity comparison, and it does — every upload re-runs the
// deterministic analysis over the whole case.
import { html, useState, useEffect, useRef } from "../../lib.js";
import * as api from "../../services/api.js";
import { Modal, Icon, Badge, ProgressBar, ErrorState } from "../ui/primitives.js";

const TYPE_OPTIONS = [
  { value: "auto", label: "Detect automatically" },
  { value: "vendor_invoice", label: "Vendor invoice" },
  { value: "purchase_order", label: "Purchase order" },
  { value: "goods_receipt_note", label: "Goods receipt note" },
  { value: "rejection_notice", label: "Rejection notice" },
  { value: "quotation", label: "Quotation / estimate" },
];

const MAX_MB = 15;

export function AddDocumentsModal({ open, exceptionId, onClose, onUploaded }) {
  const [queue, setQueue] = useState([]);
  const [phase, setPhase] = useState("select"); // select | uploading | error
  const [progress, setProgress] = useState(0);
  // Per-document extraction state from the server, polled while the upload
  // request is still open. See CreateExceptionModal for the same pattern.
  const [extractProgress, setExtractProgress] = useState(null);
  const [error, setError] = useState(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (!open) {
      setQueue([]); setPhase("select"); setProgress(0); setError(null);
      setExtractProgress(null);
    }
  }, [open]);

  const addFiles = (fileList) => {
    setQueue((prev) => [...prev, ...Array.from(fileList || []).map((file) => ({
      id: `${file.name}-${file.size}-${Math.random().toString(36).slice(2, 7)}`,
      file,
      documentType: "auto",
      invalid: !file.name.toLowerCase().endsWith(".pdf") || file.size > MAX_MB * 1024 * 1024,
    }))]);
  };

  const valid = queue.filter((f) => !f.invalid);

  const upload = async () => {
    if (!valid.length) return;
    setPhase("uploading");
    setProgress(0);
    let polling = true;
    (async () => {
      while (polling) {
        const snapshot = await api.getProgress(exceptionId);
        if (!polling) break;
        if (snapshot && snapshot.source !== "error" && snapshot.data) setExtractProgress(snapshot.data);
        await new Promise((resolveDelay) => setTimeout(resolveDelay, 1200));
      }
    })();

    const r = await api.uploadDocuments(
      exceptionId,
      valid.map((f) => ({ file: f.file, documentType: f.documentType })),
      { onProgress: setProgress },
    );
    polling = false;
    setExtractProgress(null);
    if (r.source === "error") { setError(r.error); setPhase("error"); return; }
    onUploaded(r.data);
  };

  return html`
    <${Modal} open=${open} onClose=${onClose} wide=${true} label="Add documents to this case">
      <div class="stack gap-16">
        <div class="row" style=${{ justifyContent: "space-between" }}>
          <h3 class="text-section-title">Add documents to this case</h3>
          <button class="btn btn-ghost btn-sm" onClick=${onClose} aria-label="Close dialog">
            <${Icon} name="close" size=${15} />
          </button>
        </div>

        ${phase === "error" ? html`
          <${ErrorState} title="Upload failed" message=${error}
            onRetry=${() => { setPhase("select"); setError(null); }} />
        ` : html`
          <p class="text-secondary text-small">
            Adding evidence re-runs the deterministic match over every document on this case.
          </p>

          <div class="panel-elevated stack gap-8"
            style=${{ padding: 24, alignItems: "center", textAlign: "center", cursor: "pointer", border: "1.5px dashed var(--border-strong)" }}
            onClick=${() => inputRef.current && inputRef.current.click()}
            onKeyDown=${(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); inputRef.current?.click(); } }}
            onDragOver=${(e) => e.preventDefault()}
            onDrop=${(e) => { e.preventDefault(); addFiles(e.dataTransfer.files); }}
            role="button" tabIndex="0" aria-label="Add PDF documents">
            <${Icon} name="upload" size=${22} />
            <span style=${{ fontWeight: 600 }}>Drop PDFs here, or click to choose</span>
            <span class="text-muted text-small">PDF only · up to ${MAX_MB} MB each</span>
            <input ref=${inputRef} type="file" accept="application/pdf,.pdf" multiple
              style=${{ display: "none" }}
              onChange=${(e) => { addFiles(e.target.files); e.target.value = ""; }} />
          </div>

          ${queue.map((f) => html`
            <div key=${f.id} class="panel-elevated row gap-12" style=${{ padding: 12 }}>
              <${Icon} name="file" size=${16} />
              <span style=${{ flex: 1, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                ${f.file.name}
              </span>
              ${f.invalid ? html`<${Badge} tone="exception">Not accepted<//>` : html`
                <select class="input input-sm" aria-label=${`Document type for ${f.file.name}`}
                  value=${f.documentType} disabled=${phase === "uploading"}
                  onChange=${(e) => setQueue((prev) => prev.map((q) => q.id === f.id ? { ...q, documentType: e.target.value } : q))}>
                  ${TYPE_OPTIONS.map((o) => html`<option key=${o.value} value=${o.value}>${o.label}</option>`)}
                </select>
              `}
              <button class="btn btn-ghost btn-sm" disabled=${phase === "uploading"}
                onClick=${() => setQueue((prev) => prev.filter((q) => q.id !== f.id))}
                aria-label=${`Remove ${f.file.name}`}>
                <${Icon} name="close" size=${14} />
              </button>
            </div>
          `)}

          ${phase === "uploading" ? html`
            <div class="stack gap-8">
              <${ProgressBar}
                value=${progress < 100 ? progress : (extractProgress ? extractProgress.percent : 100)}
                label=${progress < 100
                  ? "Uploading"
                  : extractProgress && extractProgress.total
                    ? `Reading documents — ${extractProgress.finished} of ${extractProgress.total}`
                    : "Extracting and re-matching…"} />
              ${progress >= 100 && extractProgress && extractProgress.active_document ? html`
                <div class="text-muted text-small">
                  Analyzing ${extractProgress.active_document.file_name}
                </div>
              ` : null}
            </div>
          ` : null}

          <div class="row gap-8" style=${{ justifyContent: "flex-end" }}>
            <button class="btn btn-ghost" onClick=${onClose} disabled=${phase === "uploading"}>Cancel</button>
            <button class="btn btn-primary" disabled=${!valid.length || phase === "uploading"} onClick=${upload}>
              ${phase === "uploading" ? "Processing…" : `Upload ${valid.length} document${valid.length === 1 ? "" : "s"}`}
            </button>
          </div>
        `}
      </div>
    <//>
  `;
}
