// CreateExceptionModal.js — the real ingestion entry point.
//
// This used to be a picker over the three seeded cases, with copy admitting
// upload wasn't wired to a route. It now creates a case and uploads PDFs to
// it for real.
//
// Deliberately NOT a fixed four-slot form. A case takes as many documents as
// the investigation needs, in any order, and more can be added later — a
// corrected invoice, a goods receipt that turns up two days on. Each file's
// type is auto-detected from its own text and can be overridden per file.
//
// A missing purchase order or goods receipt is never an upload error. The
// only thing that blocks analysis is having no readable vendor invoice, and
// the modal says so in those words.
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

const TYPE_LABEL = Object.fromEntries(TYPE_OPTIONS.map((o) => [o.value, o.label]));
const MAX_MB = 15;

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function CreateExceptionModal({ open, onClose, onOpenExisting }) {
  // What the person wants to call this case. Optional, and left empty the
  // case is displayed under its generated reference exactly as before —
  // "EXC-2026-A3F81B04" is a fine primary key and a poor thing to say out
  // loud in a stand-up, but nobody should be made to name a case before they
  // have looked at the documents.
  const [title, setTitle] = useState("");
  const [queue, setQueue] = useState([]);        // [{ file, documentType, id }]
  const [phase, setPhase] = useState("select");  // select | uploading | analyzing | done | error
  const [progress, setProgress] = useState(0);
  // Server-side extraction progress, polled while the upload request is still
  // open. Null until the first poll answers.
  const [extractProgress, setExtractProgress] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    if (!open) {
      setQueue([]); setPhase("select"); setProgress(0); setResult(null);
      setError(null); setTitle("");
    }
  }, [open]);

  const addFiles = (fileList) => {
    const incoming = Array.from(fileList || []).map((file) => ({
      id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 7)}`,
      file,
      documentType: "auto",
      tooBig: file.size > MAX_MB * 1024 * 1024,
      wrongType: !file.name.toLowerCase().endsWith(".pdf"),
    }));
    setQueue((prev) => [...prev, ...incoming]);
    setError(null);
  };

  const removeFile = (id) => setQueue((prev) => prev.filter((f) => f.id !== id));
  const setType = (id, documentType) =>
    setQueue((prev) => prev.map((f) => (f.id === id ? { ...f, documentType } : f)));

  const valid = queue.filter((f) => !f.tooBig && !f.wrongType);

  const handleUpload = async () => {
    if (!valid.length) return;
    setPhase("uploading");
    setProgress(0);
    setError(null);

    // "Add more documents" keeps the case that was just created rather than
    // opening a second one — a case is meant to accumulate evidence.
    let exceptionId = result && result.exceptionId;
    if (!exceptionId) {
      const created = await api.createException(title.trim() ? { title: title.trim() } : {});
      if (created.source === "error") {
        setError(created.error);
        setPhase("error");
        return;
      }
      exceptionId = created.data.exception_id;
    }

    // Reading four documents takes far longer than sending them. Poll the
    // per-document state so the wait names what it is doing; the upload
    // promise below is what actually completes the step.
    let polling = true;
    const pollProgress = async () => {
      while (polling) {
        const snapshot = await api.getProgress(exceptionId);
        if (!polling) break;
        if (snapshot && snapshot.source !== "error" && snapshot.data) {
          setExtractProgress(snapshot.data);
        }
        await new Promise((r) => setTimeout(r, 1200));
      }
    };
    pollProgress();

    const uploaded = await api.uploadDocuments(
      exceptionId,
      valid.map((f) => ({ file: f.file, documentType: f.documentType })),
      { onProgress: setProgress },
    );
    polling = false;
    setExtractProgress(null);

    if (uploaded.source === "error") {
      setError(uploaded.error);
      setPhase("error");
      return;
    }

    setResult((prev) => ({
      exceptionId,
      ...uploaded.data,
      // Keep documents from earlier batches visible in the summary.
      documents: [...((prev && prev.documents) || []), ...(uploaded.data.documents || [])],
    }));
    setQueue([]);
    setPhase("done");
  };

  const analysis = result && result.analysis;
  const canAnalyze = analysis && analysis.readiness && analysis.readiness.can_analyze;

  return html`
    <${Modal} open=${open} onClose=${onClose} wide=${true} label="New case from PDFs">
      <div class="stack gap-16">
        <div class="row" style=${{ justifyContent: "space-between" }}>
          <h3 class="text-section-title">New exception case</h3>
          <button class="btn btn-ghost btn-sm" onClick=${onClose} aria-label="Close dialog">
            <${Icon} name="close" size=${15} />
          </button>
        </div>

        ${phase === "select" || phase === "uploading" ? html`
          <p class="text-secondary text-small">
            Add the invoice and whatever supporting documents you have. There is no limit on how many
            documents a case can hold, and you can add more at any time. A missing purchase order or
            goods receipt is reported as a finding — not an upload error.
          </p>

          <label class="stack gap-4">
            <span class="text-small" style=${{ fontWeight: 600 }}>
              Case name <span class="text-muted" style=${{ fontWeight: 400 }}>(optional)</span>
            </span>
            <input class="input" type="text" maxLength="120" value=${title}
              placeholder="e.g. Q3 pipe delivery dispute — leave blank to use a reference"
              disabled=${phase === "uploading"}
              onInput=${(e) => setTitle(e.target.value)} />
            <span class="text-muted text-small">
              A label for you and your team. It is never used to match documents or classify
              the exception — every figure still comes from the PDFs.
            </span>
          </label>

          <div
            class="panel-elevated stack gap-8"
            style=${{
              padding: 28, alignItems: "center", textAlign: "center", cursor: "pointer",
              border: `1.5px dashed ${dragging ? "var(--accent)" : "var(--border-strong)"}`,
              background: dragging ? "rgba(56,189,248,0.06)" : undefined,
            }}
            onClick=${() => inputRef.current && inputRef.current.click()}
            onKeyDown=${(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); inputRef.current?.click(); } }}
            onDragOver=${(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave=${() => setDragging(false)}
            onDrop=${(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }}
            role="button" tabIndex="0" aria-label="Add PDF documents"
          >
            <${Icon} name="upload" size=${24} />
            <span style=${{ fontWeight: 600 }}>Drop PDFs here, or click to choose</span>
            <span class="text-muted text-small">PDF only · up to ${MAX_MB} MB each · as many as you need</span>
            <input ref=${inputRef} type="file" accept="application/pdf,.pdf" multiple
              style=${{ display: "none" }}
              onChange=${(e) => { addFiles(e.target.files); e.target.value = ""; }} />
          </div>

          ${queue.length ? html`
            <div class="stack gap-8">
              ${queue.map((f) => html`
                <div key=${f.id} class="panel-elevated row gap-12" style=${{ padding: 12, alignItems: "center" }}>
                  <${Icon} name="file" size=${16} />
                  <div class="stack gap-2" style=${{ flex: 1, minWidth: 0 }}>
                    <span style=${{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      ${f.file.name}
                    </span>
                    <span class="text-muted text-small">${formatSize(f.file.size)}</span>
                  </div>
                  ${f.wrongType ? html`<${Badge} tone="exception">Not a PDF<//>`
                    : f.tooBig ? html`<${Badge} tone="exception">Over ${MAX_MB} MB<//>`
                    : html`
                      <select class="input input-sm" aria-label=${`Document type for ${f.file.name}`}
                        value=${f.documentType} disabled=${phase === "uploading"}
                        onChange=${(e) => setType(f.id, e.target.value)}>
                        ${TYPE_OPTIONS.map((o) => html`<option key=${o.value} value=${o.value}>${o.label}</option>`)}
                      </select>
                    `}
                  <button class="btn btn-ghost btn-sm" disabled=${phase === "uploading"}
                    onClick=${() => removeFile(f.id)} aria-label=${`Remove ${f.file.name}`}>
                    <${Icon} name="close" size=${14} />
                  </button>
                </div>
              `)}
            </div>
          ` : null}

          ${phase === "uploading" ? html`
            <div class="stack gap-8">
              <${ProgressBar}
                value=${progress < 100 ? progress : (extractProgress ? extractProgress.percent : 100)}
                label=${progress < 100
                  ? "Uploading"
                  : extractProgress && extractProgress.total
                    ? `Reading documents — ${extractProgress.finished} of ${extractProgress.total}`
                    : "Extracting and matching…"} />
              ${progress >= 100 && extractProgress && extractProgress.active_document ? html`
                <div class="text-muted text-small">
                  Analyzing ${extractProgress.active_document.file_name}
                  ${extractProgress.active_document.document_type
                    ? ` · ${String(extractProgress.active_document.document_type).replaceAll("_", " ")}`
                    : ""}
                </div>
              ` : null}
              ${progress >= 100 && extractProgress && extractProgress.documents ? html`
                <div class="stack gap-4">
                  ${extractProgress.documents.map((d) => html`
                    <div class="row gap-8 text-small" key=${d.document_id}
                      style=${{ justifyContent: "space-between" }}>
                      <span class="text-muted" style=${{ overflow: "hidden", textOverflow: "ellipsis",
                        whiteSpace: "nowrap" }}>${d.file_name}</span>
                      <${Badge} tone=${d.processing_state === "completed" ? "verified"
                        : d.processing_state === "failed" ? "danger" : "warning"}>
                        ${d.processing_state === "completed" ? "read"
                          : d.processing_state === "failed" ? "failed"
                          : d.processing_state === "processing" ? "reading…" : "queued"}
                      <//>
                    </div>
                  `)}
                </div>
              ` : null}
              ${progress >= 100 ? html`
                <div class="text-muted text-small">
                  Each document is read by the extraction agent before matching runs. This
                  usually takes a few seconds per document.
                </div>
              ` : null}
            </div>
          ` : null}

          <div class="row gap-8" style=${{ justifyContent: "flex-end", flexWrap: "wrap" }}>
            <button class="btn btn-ghost" onClick=${onClose} disabled=${phase === "uploading"}>Cancel</button>
            <button class="btn btn-primary" disabled=${!valid.length || phase === "uploading"}
              onClick=${handleUpload}>
              ${phase === "uploading" ? "Processing…"
                : html`<${Icon} name="upload" size=${15} /> Create case with ${valid.length} document${valid.length === 1 ? "" : "s"}`}
            </button>
          </div>
        ` : null}

        ${phase === "error" ? html`
          <${ErrorState} title="Upload failed" message=${error}
            onRetry=${() => { setPhase("select"); setError(null); }} />
        ` : null}

        ${phase === "done" && result ? html`
          <div class="stack gap-12">
            <div class="row gap-8" style=${{ flexWrap: "wrap" }}>
              <${Badge} tone=${canAnalyze ? "verified" : "warning"}>
                ${canAnalyze ? "Analysis complete" : "Awaiting a vendor invoice"}
              <//>
              <${Badge} tone="neutral">${result.documents.length} document${result.documents.length === 1 ? "" : "s"} processed<//>
              ${analysis && analysis.exception_type ? html`
                <${Badge} tone="exception">${String(analysis.exception_type).replaceAll("_", " ")}<//>` : null}
            </div>

            ${analysis && analysis.readiness && analysis.readiness.reference_groups
              && analysis.readiness.reference_groups.is_mixed ? html`
              <div class="panel-elevated stack gap-4"
                style=${{ padding: 14, borderLeft: "3px solid var(--warning)" }}>
                <span style=${{ fontWeight: 700 }}>These documents describe more than one order</span>
                <p class="text-muted text-small" style=${{ margin: 0 }}>
                  ${analysis.readiness.reference_groups.detail}
                </p>
              </div>
            ` : null}

            <div class="stack gap-8">
              ${result.documents.map((d) => html`
                <div key=${d.document_id} class="panel-elevated row gap-12" style=${{ padding: 12, alignItems: "center" }}>
                  <${Icon} name="file" size=${16} />
                  <div class="stack gap-2" style=${{ flex: 1, minWidth: 0 }}>
                    <span style=${{ fontWeight: 600 }}>${d.file_name}</span>
                    <span class="text-muted text-small">
                      ${TYPE_LABEL[d.document_type] || d.document_type || "Unclassified"}
                      ${d.type_source === "detected" ? " · detected" : ""}
                      ${d.confidence != null ? ` · ${Math.round(d.confidence * 100)}% field confidence` : ""}
                    </span>
                  </div>
                  <${Badge} tone=${d.processing_state === "completed" ? "verified" : "exception"}>
                    ${d.processing_state}
                  <//>
                </div>
              `)}
              ${(result.rejected || []).map((r) => html`
                <div key=${r.file_name} class="panel-elevated row gap-12" style=${{ padding: 12, alignItems: "center" }}>
                  <${Icon} name="file" size=${16} />
                  <div class="stack gap-2" style=${{ flex: 1 }}>
                    <span style=${{ fontWeight: 600 }}>${r.file_name}</span>
                    <span class="text-muted text-small">${r.detail}</span>
                  </div>
                  <${Badge} tone="exception">rejected<//>
                </div>
              `)}
            </div>

            ${!canAnalyze && analysis && analysis.readiness ? html`
              <p class="text-muted text-small">${analysis.readiness.blocking_reason}</p>
            ` : null}

            <div class="row gap-8" style=${{ justifyContent: "flex-end" }}>
              <button class="btn btn-ghost" onClick=${() => { setQueue([]); setPhase("select"); }}>
                Add more documents
              </button>
              <button class="btn btn-primary" onClick=${() => onOpenExisting(result.exceptionId)}>
                Open exception <${Icon} name="arrowRight" size=${15} />
              </button>
            </div>
          </div>
        ` : null}
      </div>
    <//>
  `;
}
