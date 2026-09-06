// DocumentsTab.js — every document on the case, with its REAL state.
//
// This previously rendered a hardcoded "Processed" badge on every row and a
// disabled "Preview unavailable" button, regardless of what had actually
// happened to the file. Now it shows the true processing state, whether the
// type was detected or set by hand, which engine produced the extraction,
// the extracted fields themselves, and a working authenticated preview.
//
// A case has no document limit, so this list is open-ended by design and
// grows as evidence arrives.
import { html, useState } from "../../lib.js";
import * as api from "../../services/api.js";
import { Badge, Icon, ProgressBar } from "../ui/primitives.js";
import { DocumentPreview } from "./DocumentPreview.js";

const TYPE_LABEL = {
  vendor_invoice: "Vendor invoice", purchase_order: "Purchase order",
  goods_receipt_note: "Goods receipt note", rejection_notice: "Rejection notice",
};

const STATE_TONE = {
  completed: "verified", processing: "accent", queued: "neutral", failed: "exception",
};

const SOURCE_LABEL = {
  ai: "Gemini extraction",
  deterministic_parser: "Deterministic parser",
};

const HIDDEN_FIELDS = new Set(["field_confidences"]);

function formatSize(bytes) {
  if (bytes == null) return null;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function DocumentRow({ document: doc, exceptionId, onRetried, onPreview }) {
  const [open, setOpen] = useState(false);
  const [retrying, setRetrying] = useState(false);

  const state = doc.processing_state || "completed";
  const extraction = doc.extraction || null;

  const retry = async () => {
    setRetrying(true);
    const r = await api.retryDocument(exceptionId, doc.document_id);
    setRetrying(false);
    if (r.source !== "error" && onRetried) onRetried();
  };

  return html`
    <div class="panel-elevated stack gap-12" style=${{ padding: 16 }}>
      <div class="row gap-16" style=${{ flexWrap: "wrap" }}>
        <div style=${{ width: 38, height: 38, borderRadius: 10, background: "rgba(56,189,248,0.12)", color: "var(--accent)", display: "flex", alignItems: "center", justifyContent: "center", flex: "none" }}>
          <${Icon} name="file" size=${18} />
        </div>
        <div class="stack gap-4" style=${{ flex: 1, minWidth: 180 }}>
          <span class="mono" style=${{ fontWeight: 600 }}>${doc.file_name}</span>
          <span class="text-muted text-small">
            ${TYPE_LABEL[doc.document_type] || doc.document_type || "Unclassified"}
            ${doc.type_source === "detected" ? " · type detected" : doc.type_source === "user" ? " · type set manually" : ""}
            · ${doc.document_id}
            ${formatSize(doc.size_bytes) ? ` · ${formatSize(doc.size_bytes)}` : ""}
          </span>
        </div>
        <${Badge} tone=${STATE_TONE[state] || "neutral"}>${state}<//>
        ${doc.confidence != null ? html`
          <span class="text-muted text-small">${Math.round(doc.confidence * 100)}% field confidence</span>
        ` : null}
        ${doc.storage_path ? html`
          <button class="btn btn-ghost btn-sm" onClick=${() => onPreview(doc)}>
            <${Icon} name="file" size=${14} /> Preview
          </button>
        ` : html`
          <span class="text-muted text-small" title="Seeded demo document — no uploaded file behind it">
            No stored file
          </span>
        `}
        ${extraction ? html`
          <button class="btn btn-ghost btn-sm" onClick=${() => setOpen((v) => !v)}
            aria-expanded=${open}>
            ${open ? "Hide fields" : "Extracted fields"} <${Icon} name="chevronDown" size=${14} />
          </button>
        ` : null}
      </div>

      ${doc.extraction_source ? html`
        <div class="row gap-8" style=${{ flexWrap: "wrap" }}>
          <${Badge} tone=${doc.extraction_source === "ai" ? "accent" : "neutral"}>
            ${SOURCE_LABEL[doc.extraction_source] || doc.extraction_source}
          <//>
          ${doc.extraction_error ? html`
            <span class="text-muted text-small">Gemini call failed; fell back to the deterministic parser.</span>
          ` : null}
        </div>
      ` : null}

      ${state === "failed" ? html`
        <div class="row gap-8" style=${{ flexWrap: "wrap" }}>
          <span class="text-small" style=${{ color: "var(--exception)" }}>${doc.error}</span>
          <button class="btn btn-secondary btn-sm" onClick=${retry} disabled=${retrying}>
            ${retrying ? "Retrying…" : "Retry"}
          </button>
        </div>
      ` : null}

      ${state === "processing" || state === "queued" ? html`
        <${ProgressBar} value=${state === "processing" ? 65 : 15} label="Processing" />
      ` : null}

      ${open && extraction ? html`
        <div class="stack gap-4" style=${{ paddingTop: 4 }}>
          <hr class="hairline" />
          ${Object.entries(extraction)
            .filter(([key, value]) => !HIDDEN_FIELDS.has(key) && value !== null && value !== undefined)
            .map(([key, value]) => html`
              <div key=${key} class="row gap-12" style=${{ justifyContent: "space-between" }}>
                <span class="text-muted text-small">${key.replaceAll("_", " ")}</span>
                <span class="text-small" style=${{ fontWeight: 600, textAlign: "right" }}>${String(value)}</span>
              </div>
            `)}
        </div>
      ` : null}
    </div>
  `;
}

export function DocumentsTab({ documents, exceptionId, dataTourAnchor, onChanged, onAddDocuments }) {
  const [previewDoc, setPreviewDoc] = useState(null);

  if (!documents || documents.length === 0) {
    return html`
      <div class="stack gap-12" data-tour=${dataTourAnchor}>
        <p class="text-muted">No documents on this case yet.</p>
        ${onAddDocuments ? html`
          <button class="btn btn-primary" style=${{ width: "fit-content" }} onClick=${onAddDocuments}>
            <${Icon} name="upload" size=${15} /> Add documents
          </button>
        ` : null}
      </div>
    `;
  }

  return html`
    <div class="stack gap-12" data-tour=${dataTourAnchor}>
      ${documents.map((d) => html`
        <${DocumentRow} key=${d.document_id} document=${d} exceptionId=${exceptionId}
          onRetried=${onChanged} onPreview=${setPreviewDoc} />
      `)}
      <${DocumentPreview} open=${Boolean(previewDoc)} document=${previewDoc}
        exceptionId=${exceptionId} onClose=${() => setPreviewDoc(null)} />
      ${onAddDocuments ? html`
        <button class="btn btn-secondary" style=${{ width: "fit-content" }} onClick=${onAddDocuments}>
          <${Icon} name="plus" size=${15} /> Add more documents
        </button>
      ` : null}
    </div>
  `;
}
