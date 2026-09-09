// DocumentPreview.js — the PDF and what was read out of it, side by side.
//
// Preview used to open a new browser tab, which breaks the one thing this
// screen is for: checking an extracted number against the document it came
// from. Comparing "unit price 2,650" to a PDF in another tab means holding a
// figure in your head while you switch context. Side by side, it is a glance.
//
// The PDF is fetched through the authenticated backend endpoint and shown
// from a blob URL, so no bucket URL is ever exposed and access is checked on
// every read.
import { html, useState, useEffect, createPortal } from "../../lib.js";
import * as api from "../../services/api.js";
import { Icon, Badge, Skeleton } from "../ui/primitives.js";

const TYPE_LABEL = {
  vendor_invoice: "Vendor invoice", purchase_order: "Purchase order",
  goods_receipt_note: "Goods receipt note", rejection_notice: "Rejection notice",
};

const HIDDEN_FIELDS = new Set(["field_confidences"]);

function confidenceFor(document, fieldName) {
  const list = (document.extraction && document.extraction.field_confidences) || [];
  const found = list.find((c) => c.field_name === fieldName);
  return found ? found.confidence : null;
}

export function DocumentPreview({ open, document: doc, exceptionId, onClose }) {
  const [blobUrl, setBlobUrl] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !doc || !doc.storage_path) return undefined;
    let revoked = null;
    let cancelled = false;

    setLoading(true);
    setError(null);
    api.fetchDocumentBlobUrl(exceptionId, doc.document_id).then((r) => {
      if (cancelled) {
        if (r.source !== "error") URL.revokeObjectURL(r.data);
        return;
      }
      setLoading(false);
      if (r.source === "error") { setError(r.error); return; }
      revoked = r.data;
      setBlobUrl(r.data);
    });

    return () => {
      cancelled = true;
      // Blob URLs pin the whole file in memory until released. A reviewer
      // flipping through a dozen documents would otherwise hold every one.
      if (revoked) URL.revokeObjectURL(revoked);
      setBlobUrl(null);
    };
  }, [open, doc, exceptionId]);

  if (!open || !doc) return null;

  const extraction = doc.extraction || null;
  const fields = extraction
    ? Object.entries(extraction).filter(([k, v]) => !HIDDEN_FIELDS.has(k) && v !== null && v !== undefined)
    : [];

  return createPortal(html`
    <div class="overlay-backdrop" role="presentation"
      onClick=${(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div class="doc-preview" role="dialog" aria-modal="true" aria-label=${`Preview of ${doc.file_name}`}>
        <div class="doc-preview-head">
          <${Icon} name="file" size=${17} />
          <div class="stack gap-2" style=${{ flex: 1, minWidth: 0 }}>
            <span style=${{ fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              ${doc.file_name}
            </span>
            <span class="text-muted text-small">
              ${TYPE_LABEL[doc.document_type] || doc.document_type}
              ${doc.type_source === "detected" ? " · type detected" : ""}
            </span>
          </div>
          ${doc.extraction_source ? html`
            <${Badge} tone=${doc.extraction_source === "ai" ? "accent" : "neutral"}>
              ${doc.extraction_source === "ai" ? "Gemini extraction" : "Deterministic parser"}
            <//>
          ` : null}
          <button class="btn btn-ghost btn-sm" onClick=${onClose} aria-label="Close preview">
            <${Icon} name="close" size=${16} />
          </button>
        </div>

        <div class="doc-preview-body">
          <div class="doc-preview-pdf">
            ${loading ? html`<${Skeleton} height="100%" />`
              : error ? html`
                <div class="stack gap-8" style=${{ padding: 24, textAlign: "center" }}>
                  <span class="text-small" style=${{ color: "var(--exception)" }}>${error}</span>
                </div>`
              : blobUrl ? html`
                <object data=${blobUrl} type="application/pdf" class="doc-preview-object"
                  aria-label=${`PDF preview of ${doc.file_name}`}>
                  <div class="stack gap-8" style=${{ padding: 24, textAlign: "center" }}>
                    <span class="text-muted text-small">
                      This browser will not display the PDF inline.
                    </span>
                    <a class="btn btn-secondary btn-sm" href=${blobUrl} target="_blank" rel="noopener">
                      Open in a new tab
                    </a>
                  </div>
                </object>`
              : html`
                <div class="stack gap-8" style=${{ padding: 24, textAlign: "center" }}>
                  <span class="text-muted text-small">
                    This is a seeded demo document — there is no uploaded file behind it.
                  </span>
                </div>`}
          </div>

          <div class="doc-preview-fields">
            <div class="stack gap-2" style=${{ marginBottom: 12 }}>
              <span class="text-section-title" style=${{ fontSize: 15 }}>Extracted fields</span>
              <span class="text-muted text-small">
                Read from this document. Check any value against the page beside it.
              </span>
            </div>
            ${fields.length === 0 ? html`
              <p class="text-muted text-small">No fields were extracted from this document.</p>
            ` : html`
              <div class="stack gap-2">
                ${fields.map(([key, value]) => {
                  const confidence = confidenceFor(doc, key);
                  return html`
                    <div class="doc-field" key=${key}>
                      <span class="text-muted text-small">${key.replaceAll("_", " ")}</span>
                      <span class="doc-field-value">${String(value)}</span>
                      ${confidence !== null ? html`
                        <span class="text-muted text-small doc-field-confidence"
                          title=${`Extraction confidence for this field`}>
                          ${Math.round(confidence * 100)}%
                        </span>
                      ` : null}
                    </div>
                  `;
                })}
              </div>
            `}
          </div>
        </div>
      </div>
    </div>
  `, document.body);
}
