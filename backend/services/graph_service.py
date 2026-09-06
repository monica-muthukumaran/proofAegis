"""
graph_service.py — FR-008 (evidence graph), FR-009 (inline citations).

Deliberately NOT an AI component (see the pack's change #2: "the thing that's
supposed to *prove* your evidence chain" cannot be allowed to hallucinate it).
This assembles a graph purely from a MatchResult and the source documents
already on file — every node and edge is traceable to a value that
matching_service.py computed or a document that was actually extracted.
"""
from __future__ import annotations

from schemas import ComparisonField, EvidenceGraph, GraphEdge, GraphNode, GraphNodeType, MatchResult

# Which document type actually supplies each side of a comparison. This is the
# difference between a graph that PROVES provenance and one that merely asserts
# it: previously every extracted value was linked to every document on the
# case, so the graph claimed the unit price came from the goods receipt and the
# rejection notice as well as from the invoice and PO. Three of those four
# edges were false, on the one screen whose entire job is being checkable.
#
# "expected" is the authorising document, "actual" is the invoice being tested.
_FIELD_SOURCES = {
    ComparisonField.VENDOR: ("purchase_order", "vendor_invoice"),
    ComparisonField.PO_NUMBER: ("purchase_order", "vendor_invoice"),
    ComparisonField.UNIT_PRICE: ("purchase_order", "vendor_invoice"),
    ComparisonField.TOTAL: ("purchase_order", "vendor_invoice"),
    ComparisonField.TAX: ("purchase_order", "vendor_invoice"),
    # Quantity is checked against what was RECEIVED, not what was ordered.
    ComparisonField.QUANTITY: ("goods_receipt_note", "vendor_invoice"),
}


def build_evidence_graph(exception_id: str, documents: list[dict], match_result: MatchResult,
                          tolerance: dict, source_documents: dict | None = None) -> EvidenceGraph:
    nodes: list[GraphNode] = []
    edge_list: list[GraphEdge] = []
    # Collected as findings are emitted, so the routing nodes below can be
    # attached to each of them.
    finding_node_ids: list[str] = []
    edge_seq = 0

    def next_edge_id() -> str:
        nonlocal edge_seq
        edge_seq += 1
        return f"{exception_id}-edge-{edge_seq}"

    # role -> document_id, recorded during ingestion. Falls back to the first
    # document of each type for seeded cases that predate that field.
    if not source_documents:
        source_documents = {}
        for doc in documents:
            doc_type = doc.get("document_type")
            if doc_type and doc_type not in source_documents:
                source_documents[doc_type] = doc["document_id"]

    # --- Document nodes ---
    doc_node_ids: dict[str, str] = {}
    document_id_to_node: dict[str, str] = {}
    for doc in documents:
        node_id = f"doc-{doc['document_id']}"
        doc_node_ids[doc["document_type"]] = node_id
        document_id_to_node[doc["document_id"]] = node_id
        nodes.append(GraphNode(
            id=node_id,
            type=GraphNodeType.DOCUMENT,
            label=doc.get("file_name", doc["document_type"]),
            detail=f"Type: {doc['document_type']} · Confidence: {doc.get('confidence', 'n/a')}",
            source_document_id=doc["document_id"],
        ))

    # --- Business rule node (the tolerance config actually applied) ---
    rule_node_id = f"{exception_id}-rule-tolerance"
    nodes.append(GraphNode(
        id=rule_node_id,
        type=GraphNodeType.BUSINESS_RULE,
        label="Tolerance rule",
        detail=(f"Price tolerance {tolerance['price_variance_percent']}% · "
                f"Quantity tolerance {tolerance['quantity_variance_percent']}% "
                f"(settings/tolerance_rules)"),
    ))

    # --- Extracted-value + finding nodes, one pair per evaluable comparison ---
    for i, cmp in enumerate(match_result.comparisons):
        if not cmp.evaluable:
            continue

        value_node_id = f"{exception_id}-value-{cmp.field.value}"
        nodes.append(GraphNode(
            id=value_node_id,
            type=GraphNodeType.EXTRACTED_VALUE,
            label=f"{cmp.field.value}: expected {cmp.expected_value} / actual {cmp.actual_value}",
            detail=(f"variance {cmp.percentage_variance}%" if cmp.percentage_variance is not None else None),
        ))

        # Link the extracted value only to the documents it genuinely came
        # from — the authorising document for the expected side, the invoice
        # for the actual side. A document that supplied neither gets no edge.
        for role in _FIELD_SOURCES.get(cmp.field, ()):
            document_id = source_documents.get(role)
            target_node = document_id_to_node.get(document_id) if document_id else doc_node_ids.get(role)
            if not target_node:
                continue
            edge_list.append(GraphEdge(
                id=next_edge_id(), source=value_node_id, target=target_node, relationship="extracted_from",
            ))

        # Link the value to the tolerance rule it was evaluated against.
        edge_list.append(GraphEdge(
            id=next_edge_id(), source=value_node_id, target=rule_node_id, relationship="evaluated_against",
        ))

        # A finding node only for comparisons that actually produced a variance signal.
        if cmp.classification.value in ("outside_tolerance", "within_tolerance"):
            finding_node_id = f"{exception_id}-finding-{cmp.field.value}"
            finding_node_ids.append(finding_node_id)
            nodes.append(GraphNode(
                id=finding_node_id,
                type=GraphNodeType.FINDING,
                label=f"{cmp.classification.value.replace('_', ' ').title()}: {cmp.field.value}",
                detail=f"{match_result.exception_type.value} — financial impact basis: {match_result.financial_impact_basis}",
            ))
            edge_list.append(GraphEdge(
                id=next_edge_id(), source=value_node_id, target=finding_node_id, relationship="produces",
            ))

    # --- Where the case goes next ----------------------------------------
    # The graph used to end at the finding, which left the one screen whose
    # job is to answer "how did you get here" silent on "so what now". Both
    # of these are echoed verbatim from the deterministic MatchResult — the
    # matcher decided the owner and the action, and this only draws them, in
    # keeping with this module's rule that it assembles and never derives.
    #
    # Attached to every finding rather than to the case, so a graph with two
    # findings shows both of them arriving at the same owner instead of the
    # routing appearing to float free of the evidence.
    if finding_node_ids:
        owner_node_id = f"{exception_id}-routing-owner"
        nodes.append(GraphNode(
            id=owner_node_id,
            type=GraphNodeType.ROUTING,
            label="Recommended owner",
            detail=match_result.recommended_owner,
        ))
        action_node_id = f"{exception_id}-routing-action"
        nodes.append(GraphNode(
            id=action_node_id,
            type=GraphNodeType.ROUTING,
            label="Recommended action",
            detail=_recommended_action(match_result),
        ))
        for finding_node_id in finding_node_ids:
            for target in (owner_node_id, action_node_id):
                edge_list.append(GraphEdge(
                    id=next_edge_id(), source=finding_node_id, target=target,
                    relationship="routed_to",
                ))

    return EvidenceGraph(nodes=nodes, edges=edge_list)


# What a reviewer should do about each exception type. A lookup rather than a
# generated sentence, deliberately: this node sits in the evidence graph, and
# every other node in it is traceable to a document or a computation. A model
# writing this one would make the graph the only place in the product where
# provenance is "the AI said so".
#
# The resolution copilot still drafts the actual message — that is language,
# and it cites its sources. This is the one-line label on a box.
_ACTION_BY_TYPE = {
    "price_variance": "Vendor correction request",
    "quantity_variance": "Confirm receipt with Receiving",
    "missing_goods_receipt": "Obtain delivery confirmation",
    "missing_purchase_order": "Locate or raise the purchase order",
    "vendor_mismatch": "Confirm the billing entity",
    "tax_total_mismatch": "Ask the vendor to restate the invoice",
    "duplicate_invoice": "Hold payment; confirm re-submission",
    "po_over_billed": "Amend the order or reject the excess",
    "payment_details_changed": "Verify the account out of band",
    "recurring_suspected": "Confirm this is not a second copy",
    "vendor_price_drift": "Re-quote or check the escalation clause",
    "no_exception": "No action required",
}


def _recommended_action(match_result: MatchResult) -> str:
    return _ACTION_BY_TYPE.get(
        match_result.exception_type.value, "Review and route manually")
