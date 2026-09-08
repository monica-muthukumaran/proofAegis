import { html, useState, useEffect } from "../lib.js";
import * as api from "../services/api.js";
import { ExceptionSummary } from "../components/exceptions/ExceptionSummary.js";
import { MatchWorkspace } from "../components/exceptions/MatchWorkspace.js";
import { DocumentsTab } from "../components/exceptions/DocumentsTab.js";
import { AuditTab } from "../components/exceptions/AuditTab.js";
import { ExceptionStatus } from "../components/exceptions/ExceptionStatus.js";
import { EvidenceGraph } from "../components/graph/EvidenceGraph.js";
import { EvidenceDetailsDrawer } from "../components/graph/EvidenceDetailsDrawer.js";
import { ResolutionAssistant } from "../components/resolutions/ResolutionAssistant.js";
import { Skeleton, Badge, Icon, ErrorState } from "../components/ui/primitives.js";
import { AddDocumentsModal } from "../components/exceptions/AddDocumentsModal.js";
import { HypothesisPanel } from "../components/exceptions/HypothesisPanel.js";

const TABS = [
  { key: "summary", label: "Summary" },
  { key: "documents", label: "Documents" },
  { key: "match", label: "Match" },
  { key: "graph", label: "Evidence graph" },
  // Sits between the evidence and the draft, which is where it belongs in the
  // reviewer's own order of work: read what was found, decide what to check,
  // then write to somebody about it.
  { key: "investigate", label: "Investigate" },
  { key: "resolution", label: "Resolution" },
  { key: "audit", label: "Audit trail" },
];

export function ExceptionDetail({ exceptionId, onBack, forcedTab }) {
  const [exception, setException] = useState(null);
  const [matchResult, setMatchResult] = useState(null);
  const [documents, setDocuments] = useState(null);
  const [graph, setGraph] = useState(null);
  const [auditEvents, setAuditEvents] = useState(null);
  const [tab, setTab] = useState(forcedTab || "summary");
  const [selectedNode, setSelectedNode] = useState(null);
  const [readiness, setReadiness] = useState(null);
  const [trustCheck, setTrustCheck] = useState(null);
  const [error, setError] = useState(null);
  const [addOpen, setAddOpen] = useState(false);
  const [renamingTitle, setRenamingTitle] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");

  // An empty box means "go back to showing the reference", which is a real
  // thing to want after naming a case by mistake — so it sends null rather
  // than refusing to save.
  const saveTitle = async () => {
    const next = draftTitle.trim() || null;
    setRenamingTitle(false);
    if (next === (exception.title || null)) return;
    const saved = await api.renameException(exceptionId, next);
    if (saved.source === "error") { setError(saved.error); return; }
    setException((prev) => ({ ...prev, title: next }));
    // The rename is an audit event, so the trail on screen is now stale.
    const refreshed = await api.getAudit(exceptionId);
    if (refreshed.source !== "error") setAuditEvents(refreshed.data);
  };

  useEffect(() => { if (forcedTab) setTab(forcedTab); }, [forcedTab]);

  const loadAll = async () => {
    setError(null);
    const [excRes, matchRes, docsRes, graphRes, auditRes, readyRes, trustRes] = await Promise.all([
      api.getException(exceptionId), api.getMatch(exceptionId), api.getDocuments(exceptionId),
      api.getGraph(exceptionId), api.getAudit(exceptionId), api.getReadiness(exceptionId),
      api.getTrustCheck(exceptionId),
    ]);
    if (excRes.source === "error") { setError(excRes.error); return; }
    setException(excRes.data);
    // Absent until the reasoning agent has run on this case. That is a real
    // state, not a failure: before the model has stated a figure there is
    // nothing for the guardrail to have compared it against.
    setTrustCheck(trustRes.source === "error" ? null : trustRes.data);
    // A case with no invoice yet has no match result. That is a legitimate
    // state, not a failure — the page renders the documents tab and says
    // what is missing instead of spinning forever on a skeleton.
    setMatchResult(matchRes.source === "error" ? null : matchRes.data);
    setDocuments(docsRes.source === "error" ? [] : docsRes.data);
    setGraph(graphRes.source === "error" ? null : graphRes.data);
    setAuditEvents(auditRes.source === "error" ? [] : auditRes.data);
    setReadiness(readyRes.source === "error" ? null : readyRes.data);
  };

  useEffect(() => { loadAll(); }, [exceptionId]);

  const handleCitationOpen = (citation) => {
    setSelectedNode({ id: citation.source_document_id, type: "document", label: citation.claim, source_document_id: citation.source_document_id, detail: `field: ${citation.source_field}` });
  };

  const handleStatusChanged = (updated) => {
    setException((prev) => ({ ...prev, status: updated.status }));
    api.getAudit(exceptionId).then((r) => setAuditEvents(r.data));
  };

  if (error) {
    return html`<div class="panel"><${ErrorState} title="Could not load this exception" message=${error} onRetry=${loadAll} /></div>`;
  }

  if (!exception) {
    return html`
      <div class="stack gap-16">
        <${Skeleton} height="32px" width="240px" />
        <${Skeleton} height="200px" />
      </div>
    `;
  }

  const awaitingInvoice = !matchResult;

  const tabContent = {
    summary: awaitingInvoice
      ? html`<div class="stack gap-12">
          <p class="text-secondary">
            ${(readiness && readiness.blocking_reason) ||
              "This case needs a readable vendor invoice before it can be analyzed."}
          </p>
          <button class="btn btn-primary" style=${{ width: "fit-content" }} onClick=${() => setAddOpen(true)}>
            <${Icon} name="upload" size=${15} /> Add documents
          </button>
        </div>`
      : html`<${ExceptionSummary} exception=${exception} matchResult=${matchResult} documents=${documents} graph=${graph} />`,
    documents: html`<${DocumentsTab} documents=${documents} exceptionId=${exceptionId}
      dataTourAnchor="sample-documents" onChanged=${loadAll} onAddDocuments=${() => setAddOpen(true)} />`,
    match: awaitingInvoice
      ? html`<p class="text-muted">Nothing to compare yet — add a vendor invoice to run the match.</p>`
      : html`<div data-tour="extracted-fields"><div data-tour="match-workspace"><${MatchWorkspace} matchResult=${matchResult} trustCheck=${trustCheck} linkWarnings=${(exception && exception.source_documents && exception.source_documents.link_warnings) || []} /></div></div>`,
    investigate: awaitingInvoice
      ? html`<p class="text-muted">Nothing to investigate yet — add a vendor invoice to run the match.</p>`
      : html`<${HypothesisPanel} exceptionId=${exceptionId} />`,
    graph: awaitingInvoice
      ? html`<p class="text-muted">The evidence graph appears once the case has been analyzed.</p>`
      : html`<div data-tour="evidence-graph"><${EvidenceGraph} graph=${graph} onSelectNode=${setSelectedNode} /></div><div data-tour="source-citations" style=${{ marginTop: 12 }} class="text-muted text-small">Click any node above to open its source detail.</div>`,
    resolution: awaitingInvoice
      ? html`<p class="text-muted">A resolution draft needs an analyzed exception first.</p>`
      : html`<div data-tour="resolution-draft"><${ResolutionAssistant} exceptionId=${exceptionId} onOpenCitation=${handleCitationOpen} /></div>`,
    audit: html`<div data-tour="audit-trail"><${AuditTab} events=${auditEvents} /></div>`,
  };

  return html`
    <div class="stack gap-20">
      <button class="btn btn-ghost btn-sm" style=${{ width: "fit-content" }} onClick=${onBack}>
        <${Icon} name="arrowLeft" size=${14} /> Back to exceptions
      </button>

      <div class="row gap-16" style=${{ flexWrap: "wrap", justifyContent: "space-between" }}>
        <div class="stack gap-4">
          ${renamingTitle
            ? html`
              <div class="row gap-8" style=${{ flexWrap: "wrap" }}>
                <input class="input" type="text" maxLength="120" autoFocus
                  value=${draftTitle} aria-label="Case name"
                  placeholder="Name this case — leave blank to use its reference"
                  onInput=${(e) => setDraftTitle(e.target.value)}
                  onKeyDown=${(e) => {
                    if (e.key === "Enter") saveTitle();
                    if (e.key === "Escape") setRenamingTitle(false);
                  }} />
                <button class="btn btn-primary btn-sm" onClick=${saveTitle}>Save</button>
                <button class="btn btn-ghost btn-sm" onClick=${() => setRenamingTitle(false)}>Cancel</button>
              </div>
            `
            : html`
              <div class="row gap-8" style=${{ alignItems: "baseline", flexWrap: "wrap" }}>
                <h1 class="text-page-title ${exception.title ? "" : "mono"}" style=${{ fontSize: 24 }}>
                  ${exception.title || exception.exception_id}
                </h1>
                <button class="btn btn-ghost btn-sm"
                  aria-label=${exception.title ? "Rename this case" : "Name this case"}
                  onClick=${() => { setDraftTitle(exception.title || ""); setRenamingTitle(true); }}>
                  ${exception.title ? "Rename" : "Name this case"}
                </button>
              </div>
            `}
          <p class="text-secondary">
            ${/* The generated reference stays on screen once a title replaces it in
                 the heading. It is what every other system and every audit event
                 calls this case, so it must remain quotable. */
              exception.title
                ? html`<span class="id">${exception.exception_id}</span> · `
                : null}
            <span class="id">${exception.invoice_id}</span> · ${exception.vendor_name}
          </p>
        </div>
        ${matchResult
          ? html`<${Badge} tone="exception">${matchResult.awaiting_document ? `missing ${matchResult.awaiting_document}` : matchResult.exception_type.replaceAll("_", " ")}<//>`
          : html`<${Badge} tone="neutral">Awaiting documents<//>`}
      </div>

      <div class="panel" style=${{ padding: 18 }}>
        <${ExceptionStatus} exceptionId=${exceptionId} status=${exception.status} onChanged=${handleStatusChanged} />
      </div>

      <div class="tabs" role="tablist" aria-label="Exception workspace sections">
        ${TABS.map((t) => html`
          <button key=${t.key} role="tab" aria-selected=${tab === t.key} class="tab-btn ${tab === t.key ? "active" : ""}" onClick=${() => setTab(t.key)}>${t.label}</button>
        `)}
      </div>

      <div class="panel" role="tabpanel" style=${{ padding: 24, minHeight: 320 }}>
        ${tabContent[tab]}
      </div>

      <${EvidenceDetailsDrawer} node=${selectedNode} onClose=${() => setSelectedNode(null)} />
      <${AddDocumentsModal} open=${addOpen} exceptionId=${exceptionId}
        onClose=${() => setAddOpen(false)}
        onUploaded=${() => { setAddOpen(false); loadAll(); }} />
    </div>
  `;
}
