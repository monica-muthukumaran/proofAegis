"""
datastore.py — a small repository layer so routes never talk to Firestore
(or to the mock JSON) directly.

Two implementations:
  - FirestoreDatastore: real reads/writes against the collections in
    Document 2 §7 (invoice_exceptions, documents, resolution_drafts,
    audit_events, settings).
  - InMemoryDatastore: seeded from mock_data/seed_cases.json, used whenever
    config.USE_MOCK_DATA is true. This is also what the test suite runs
    against, since this sandbox has no live GCP credentials.

get_datastore() picks the right one once, at import time.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Optional

from config import config

_SEED_PATH = os.path.join(os.path.dirname(__file__), "mock_data", "seed_cases.json")
# Optional bulk portfolio from scripts/generate_synthetic_data.py. Gitignored
# and absent by default; when present it loads alongside the three hero cases
# so the analytics screens have a population to describe. The hero cases keep
# their full matching_input and stay fully investigable — portfolio records
# are analytics fodder carrying pre-computed outcomes.
_PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "data", "generated", "portfolio.json")


class InMemoryDatastore:
    def __init__(self, seed_path: str = _SEED_PATH):
        with open(seed_path) as f:
            seed = json.load(f)
        self._tolerance = seed["tolerance_rules"]
        self._cases = {c["exception_id"]: copy.deepcopy(c) for c in seed["cases"]}
        self._resolution_drafts: dict[str, dict] = {}
        self._reasoning: dict[str, dict] = {}
        # Investigation hypotheses (services/hypothesis_agent.py). Cached per
        # case the same way reasoning is, so re-opening a case does not spend
        # another model call on a question already answered.
        self._hypotheses: dict[str, dict] = {}
        self._audit_events: dict[str, list[dict]] = {eid: [] for eid in self._cases}

        # Documents live in their own store keyed by document_id, the same
        # shape uploaded documents use, so get_documents() has one code path
        # whether a case was seeded or built from real uploads. A case may
        # hold any number of them.
        if os.path.isfile(_PORTFOLIO_PATH):
            with open(_PORTFOLIO_PATH, encoding="utf-8") as f:
                portfolio = json.load(f)
            for case in portfolio.get("cases", []):
                self._cases.setdefault(case["exception_id"], copy.deepcopy(case))

        self._documents: dict[str, dict] = {}
        for case in self._cases.values():
            for doc in case.pop("documents", []):
                record = copy.deepcopy(doc)
                record["exception_id"] = case["exception_id"]
                record["workspace_id"] = case.get("workspace_id", config.DEFAULT_WORKSPACE_ID)
                record.setdefault("processing_state", "completed")
                record.setdefault("origin", "seed")
                record.setdefault("uploaded_at", "2026-07-01T00:00:00+00:00")
                self._documents[record["document_id"]] = record
            case.setdefault("workspace_id", config.DEFAULT_WORKSPACE_ID)

    # --- exceptions ---
    def list_exceptions(self, workspace_id: Optional[str] = None) -> list[dict]:
        """Every case in one workspace, or in all of them when workspace_id
        is None.

        None means "no scoping asked for" and is used by the loaders and the
        eval harness, which legitimately want the whole store. Every REQUEST
        path passes a workspace, because a queue that shows another user's
        invoices is the failure this argument exists to prevent.
        """
        return [self._public_view(c) for c in self._cases.values()
                if _in_workspace(c, workspace_id)]

    def get_exception(self, exception_id: str, workspace_id: Optional[str] = None) -> Optional[dict]:
        """A case, or None when it is not this workspace's to read.

        Not-found and not-yours are deliberately the same answer here: the
        routes turn both into a 404, so a case id cannot be probed for
        existence from outside the workspace that owns it.
        """
        case = self._cases.get(exception_id)
        if case is None or not _in_workspace(case, workspace_id):
            return None
        return self._public_view(case)

    def get_matching_input(self, exception_id: str) -> Optional[dict]:
        case = self._cases.get(exception_id)
        # Portfolio records carry pre-computed outcomes and no matching_input;
        # only investigable cases (seeded or uploaded) have one. Absence is a
        # normal state, not a missing key.
        if not case:
            return None
        matching_input = case.get("matching_input")
        return copy.deepcopy(matching_input) if matching_input else None

    def get_documents(self, exception_id: str) -> list[dict]:
        return [copy.deepcopy(d) for d in self._documents.values()
                if d.get("exception_id") == exception_id]

    def get_document(self, document_id: str) -> Optional[dict]:
        doc = self._documents.get(document_id)
        return copy.deepcopy(doc) if doc else None

    def save_document(self, document: dict) -> None:
        self._documents[document["document_id"]] = copy.deepcopy(document)

    # --- case creation / partial updates (upload pipeline) ---
    def create_exception(self, case: dict) -> dict:
        self._cases[case["exception_id"]] = copy.deepcopy(case)
        self._audit_events.setdefault(case["exception_id"], [])
        return self._public_view(self._cases[case["exception_id"]])

    def update_case_fields(self, exception_id: str, fields: dict) -> Optional[dict]:
        case = self._cases.get(exception_id)
        if not case:
            return None
        case.update(copy.deepcopy(fields))
        return self._public_view(case)

    def update_status(self, exception_id: str, new_status: str) -> Optional[dict]:
        case = self._cases.get(exception_id)
        if not case:
            return None
        case["status"] = new_status
        return self._public_view(case)

    def _public_view(self, case: dict) -> dict:
        view = copy.deepcopy(case)
        view.pop("matching_input", None)
        return view

    # --- settings ---
    def find_documents_by_type(self, document_type: str, exclude_exception_id=None,
                                workspace_id: Optional[str] = None) -> list[dict]:
        """Every completed document of a type, across all cases IN ONE
        WORKSPACE.

        Duplicate invoices, cumulative billing against one purchase order and
        a vendor's changed bank details are all invisible from inside a single
        case — they are only findable by looking at what came before. This is
        the one query that crosses the case boundary.

        It crosses the case boundary and stops dead at the workspace one, and
        that limit is not incidental. These checks assert that two documents
        are THE SAME BILL. Run across workspaces, the seeded corpus would
        report a new user's first genuine invoice as a duplicate of a
        synthetic one — a confident, specific, entirely false accusation, in
        the highest-ranked finding the product has.
        """
        out = []
        for document in self._documents.values():
            if document.get("document_type") != document_type:
                continue
            if document.get("processing_state") != "completed":
                continue
            if exclude_exception_id and document.get("exception_id") == exclude_exception_id:
                continue
            if not _in_workspace(document, workspace_id):
                continue
            out.append(copy.deepcopy(document))
        return out

    def get_tolerance_rules(self, vendor_name=None, category=None) -> dict:
        return resolve_tolerance(self._tolerance, vendor_name, category)

    def get_approval_policy(self) -> dict:
        """Empty by default: an unconfigured workspace approves as before."""
        return dict(getattr(self, "_approval_policy", {}) or {})

    # --- resolution drafts ---
    def save_resolution_draft(self, exception_id: str, draft: dict) -> None:
        self._resolution_drafts[exception_id] = draft

    def get_resolution_draft(self, exception_id: str) -> Optional[dict]:
        return self._resolution_drafts.get(exception_id)

    # --- exception reasoning (FR-007) ---
    def save_reasoning(self, exception_id: str, reasoning: dict) -> None:
        self._reasoning[exception_id] = reasoning

    def save_hypotheses(self, exception_id: str, hypotheses: dict) -> None:
        self._hypotheses[exception_id] = hypotheses

    def get_hypotheses(self, exception_id: str) -> Optional[dict]:
        return copy.deepcopy(self._hypotheses.get(exception_id))

    def get_reasoning(self, exception_id: str) -> Optional[dict]:
        return self._reasoning.get(exception_id)

    # --- audit ---
    def append_audit_event(self, exception_id: str, event: dict) -> None:
        self._audit_events.setdefault(exception_id, []).append(event)

    def get_audit_events(self, exception_id: str) -> list[dict]:
        return list(self._audit_events.get(exception_id, []))


class FirestoreDatastore:
    """Thin wrapper over the real Firestore collections. Only imported/used
    when config.USE_MOCK_DATA is False, so firebase_admin is never touched
    in mock/dev/test runs."""

    def __init__(self):
        from firestore_client import get_db
        self._db = get_db()

    def list_exceptions(self, workspace_id: Optional[str] = None) -> list[dict]:
        query = self._db.collection("invoice_exceptions")
        if workspace_id is not None:
            query = query.where("workspace_id", "==", workspace_id)
        return [d.to_dict() for d in query.stream()]

    def get_exception(self, exception_id: str, workspace_id: Optional[str] = None) -> Optional[dict]:
        doc = self._db.collection("invoice_exceptions").document(exception_id).get()
        if not doc.exists:
            return None
        case = doc.to_dict()
        return case if _in_workspace(case, workspace_id) else None

    def get_matching_input(self, exception_id: str) -> Optional[dict]:
        doc = self._db.collection("invoice_exceptions").document(exception_id).get()
        if not doc.exists:
            return None
        return doc.to_dict().get("matching_input")

    def get_documents(self, exception_id: str) -> list[dict]:
        docs = (self._db.collection("documents")
                .where("exception_id", "==", exception_id).stream())
        return [d.to_dict() for d in docs]

    def get_document(self, document_id: str) -> Optional[dict]:
        doc = self._db.collection("documents").document(document_id).get()
        return doc.to_dict() if doc.exists else None

    def save_document(self, document: dict) -> None:
        self._db.collection("documents").document(document["document_id"]).set(document)

    def create_exception(self, case: dict) -> dict:
        self._db.collection("invoice_exceptions").document(case["exception_id"]).set(case)
        return case

    def update_case_fields(self, exception_id: str, fields: dict) -> Optional[dict]:
        ref = self._db.collection("invoice_exceptions").document(exception_id)
        ref.set(fields, merge=True)
        doc = ref.get()
        return doc.to_dict() if doc.exists else None

    def update_status(self, exception_id: str, new_status: str) -> Optional[dict]:
        ref = self._db.collection("invoice_exceptions").document(exception_id)
        ref.update({"status": new_status})
        doc = ref.get()
        return doc.to_dict() if doc.exists else None

    def find_documents_by_type(self, document_type: str, exclude_exception_id=None,
                                workspace_id: Optional[str] = None) -> list[dict]:
        """See InMemoryDatastore.find_documents_by_type. Needs a composite
        index on documents(workspace_id, document_type, processing_state);
        Firestore prints the creation link on the first call if it is
        missing."""
        query = (self._db.collection("documents")
                 .where("document_type", "==", document_type)
                 .where("processing_state", "==", "completed"))
        if workspace_id is not None:
            query = query.where("workspace_id", "==", workspace_id)
        out = [d.to_dict() for d in query.stream()]
        if exclude_exception_id:
            out = [d for d in out if d.get("exception_id") != exclude_exception_id]
        return out

    def get_tolerance_rules(self, vendor_name=None, category=None) -> dict:
        doc = self._db.collection("settings").document("tolerance_rules").get()
        base = doc.to_dict() if doc.exists else {
            "price_variance_percent": config.DEFAULT_PRICE_TOLERANCE_PERCENT,
            "quantity_variance_percent": config.DEFAULT_QUANTITY_TOLERANCE_PERCENT,
        }
        return resolve_tolerance(base, vendor_name, category)

    def get_approval_policy(self) -> dict:
        doc = self._db.collection("settings").document("approval_policy").get()
        return doc.to_dict() if doc.exists else {}

    def save_resolution_draft(self, exception_id: str, draft: dict) -> None:
        self._db.collection("resolution_drafts").document(exception_id).set(draft)

    def get_resolution_draft(self, exception_id: str) -> Optional[dict]:
        doc = self._db.collection("resolution_drafts").document(exception_id).get()
        return doc.to_dict() if doc.exists else None

    def save_reasoning(self, exception_id: str, reasoning: dict) -> None:
        self._db.collection("exception_reasoning").document(exception_id).set(reasoning)

    def save_hypotheses(self, exception_id: str, hypotheses: dict) -> None:
        self._db.collection("investigation_hypotheses").document(exception_id).set(hypotheses)

    def get_hypotheses(self, exception_id: str) -> Optional[dict]:
        doc = self._db.collection("investigation_hypotheses").document(exception_id).get()
        return doc.to_dict() if doc.exists else None

    def get_reasoning(self, exception_id: str) -> Optional[dict]:
        doc = self._db.collection("exception_reasoning").document(exception_id).get()
        return doc.to_dict() if doc.exists else None

    def append_audit_event(self, exception_id: str, event: dict) -> None:
        self._db.collection("audit_events").add(event)

    def get_audit_events(self, exception_id: str) -> list[dict]:
        docs = (self._db.collection("audit_events")
                .where("exception_id", "==", exception_id)
                .order_by("timestamp").stream())
        return [d.to_dict() for d in docs]



def _in_workspace(record: Optional[dict], workspace_id: Optional[str]) -> bool:
    """Whether a case or document record belongs to the asked-for workspace.

    `workspace_id=None` means the caller asked for no scoping at all and gets
    everything — the loaders, the eval harness and the seeding scripts.

    A record with NO workspace_id of its own counts as the demo workspace's.
    That is the honest reading of the data that already exists: everything
    written before per-user workspaces was written by, and for, the shared
    demo. It also means such a record can never leak into a real user's
    queue, because a real user's workspace id is never the default.
    """
    if workspace_id is None:
        return True
    return (record or {}).get("workspace_id", config.DEFAULT_WORKSPACE_ID) == workspace_id


def resolve_tolerance(base: dict, vendor_name=None, category=None) -> dict:
    """
    The tolerance that applies to THIS case, not a single global number.

    A 5% price tolerance is reasonable on commodity hardware and far too loose
    on a large services contract, so the settings record may carry overrides:

        {
          "price_variance_percent": 5,
          "quantity_variance_percent": 2,
          "by_vendor":   {"SIGMA ENGINEERING SOLUTIONS": {"price_variance_percent": 2}},
          "by_category": {"services": {"price_variance_percent": 1}}
        }

    Specificity wins: a vendor override beats a category override, which beats
    the workspace default. Overrides are merged key by key, so a rule that
    sets only a price tolerance keeps the default quantity tolerance rather
    than blanking it. The resolved record reports what applied in
    `tolerance_source`, because a reviewer asking "why was this within
    tolerance?" needs to know which rule answered.
    """
    resolved = {k: v for k, v in (base or {}).items() if not k.startswith("by_")}
    resolved["tolerance_source"] = "workspace default"

    by_category = (base or {}).get("by_category") or {}
    if category and category in by_category:
        resolved.update(by_category[category] or {})
        resolved["tolerance_source"] = f"category rule: {category}"

    by_vendor = (base or {}).get("by_vendor") or {}
    if vendor_name:
        # Vendor names are written inconsistently across documents; compare on
        # a normalized key so "SIGMA ENGINEERING SOLUTIONS" and
        # "Sigma Engineering Solutions." resolve to the same rule.
        target = _tolerance_key(vendor_name)
        for name, override in by_vendor.items():
            if _tolerance_key(name) == target:
                resolved.update(override or {})
                resolved["tolerance_source"] = f"vendor rule: {name}"
                break
    return resolved


def _tolerance_key(value) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


_datastore = None


def get_datastore():
    global _datastore
    if _datastore is None:
        _datastore = InMemoryDatastore() if config.USE_MOCK_DATA else FirestoreDatastore()
    return _datastore
