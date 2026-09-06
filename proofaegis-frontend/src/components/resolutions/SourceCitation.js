import { html } from "../../lib.js";

export function SourceCitation({ citation, onOpen }) {
  return html`
    <button
      class="badge badge-accent"
      style=${{ border: "1px solid rgba(56,189,248,0.3)", cursor: "pointer" }}
      onClick=${() => onOpen(citation)}
      title=${citation.claim}
    >
      [${citation.source_document_id} · ${citation.source_field}]
    </button>
  `;
}
