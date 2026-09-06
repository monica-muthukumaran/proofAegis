// tourSteps.js — each step names a REAL data-tour target already present in
// the actual app components (AppShell, ExceptionDetail tabs), and the
// {view, tab} the tour must switch the app to before it can highlight that
// target. This is what makes the tour a walkthrough of the real UI rather
// than a separate mockup.
export const TOUR_EXCEPTION_ID = "EXC-2026-0001";

export const TOUR_STEPS = [
  {
    key: "product-introduction",
    target: "product-introduction",
    route: { view: "dashboard" },
    title: "Welcome to ProofAegis",
    description: "ProofAegis helps Accounts Payable and Procurement teams understand and resolve blocked invoices using source-linked evidence.",
  },
  {
    key: "sample-documents",
    target: "sample-documents",
    route: { view: "exception-detail", tab: "documents" },
    title: "Start with the source documents",
    description: "This case contains a vendor invoice, purchase order, goods receipt, and rejection notice. ProofAegis uses these documents to investigate the exception.",
  },
  {
    key: "extracted-fields",
    target: "extracted-fields",
    route: { view: "exception-detail", tab: "match" },
    title: "Extracted invoice and PO values",
    description: "ProofAegis extracts structured fields such as vendor, invoice number, PO number, quantity, unit price, and total amount.",
    facts: ["PO unit price: ₹2,400", "Invoice unit price: ₹2,650", "Quantity: 100", "Tolerance: 5%"],
  },
  {
    key: "match-workspace",
    target: "match-workspace",
    route: { view: "exception-detail", tab: "match" },
    title: "Compare authorized, received, and billed values",
    description: "The match workspace compares what was ordered, what was received, and what the vendor billed. Arithmetic and tolerance calculations are deterministic — AI supports document understanding and explanation, not the math.",
    facts: ["Price variance detected", "Actual variance: 10.42%", "Allowed tolerance: 5%", "Financial impact: ₹25,000"],
  },
  {
    key: "investigation-trace",
    target: "investigation-trace",
    route: { view: "exception-detail", tab: "summary" },
    title: "See how the investigation was completed",
    description: "This trace shows the workflow: document extraction, matching, exception reasoning, evidence-graph construction, and resolution drafting.",
  },
  {
    key: "evidence-graph",
    target: "evidence-graph",
    route: { view: "exception-detail", tab: "graph" },
    title: "Follow the evidence graph",
    description: "The graph connects source documents, extracted values, rules, discrepancies, and findings — built deterministically, not by a language model.",
  },
  {
    key: "source-citations",
    target: "source-citations",
    route: { view: "exception-detail", tab: "graph" },
    title: "Every finding is source-linked",
    description: "Open a node or citation to inspect the original document, field, and extracted value supporting the finding.",
  },
  {
    key: "resolution-draft",
    target: "resolution-draft",
    route: { view: "exception-detail", tab: "resolution" },
    title: "Prepare the next action",
    description: "ProofAegis generates a source-cited vendor correction request or internal resolution note. The draft always requires human review.",
    facts: ["Recommended owner: Procurement", "Suggested action: Request a credit note or procurement approval", "Human review required: Yes"],
  },
  {
    key: "audit-trail",
    target: "audit-trail",
    route: { view: "exception-detail", tab: "audit" },
    title: "Keep the resolution auditable",
    description: "Status changes, review notes, generated drafts, and resolution actions are recorded in the audit trail.",
  },
  {
    key: "tour-complete",
    target: null,
    route: { view: "exception-detail", tab: "audit" },
    title: "ProofAegis demo complete",
    description: "ProofAegis detected the exception, proved it with source evidence, calculated the impact, prepared the next action, and preserved the workflow history.",
    isComplete: true,
  },
];
