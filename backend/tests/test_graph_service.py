import json
import os

from schemas import GraphNodeType
from services.graph_service import build_evidence_graph
from services.matching_service import evaluate_exception

SEED_PATH = os.path.join(os.path.dirname(__file__), "..", "mock_data", "seed_cases.json")
with open(SEED_PATH) as f:
    SEED = json.load(f)

TOLERANCE = SEED["tolerance_rules"]
CASE_A = next(c for c in SEED["cases"] if c["exception_id"] == "EXC-2026-0001")


def test_graph_has_a_document_node_per_source_document():
    result = evaluate_exception(CASE_A["matching_input"], TOLERANCE)
    graph = build_evidence_graph("EXC-2026-0001", CASE_A["documents"], result, TOLERANCE)
    doc_nodes = [n for n in graph.nodes if n.type == GraphNodeType.DOCUMENT]
    assert len(doc_nodes) == len(CASE_A["documents"])


def test_graph_includes_the_tolerance_rule_node():
    result = evaluate_exception(CASE_A["matching_input"], TOLERANCE)
    graph = build_evidence_graph("EXC-2026-0001", CASE_A["documents"], result, TOLERANCE)
    rule_nodes = [n for n in graph.nodes if n.type == GraphNodeType.BUSINESS_RULE]
    assert len(rule_nodes) == 1
    assert "5%" in rule_nodes[0].detail

def test_price_variance_produces_a_finding_node():
    result = evaluate_exception(CASE_A["matching_input"], TOLERANCE)
    graph = build_evidence_graph("EXC-2026-0001", CASE_A["documents"], result, TOLERANCE)
    finding_nodes = [n for n in graph.nodes if n.type == GraphNodeType.FINDING]
    assert any("unit_price" in n.id for n in finding_nodes)


def test_every_edge_endpoint_exists_as_a_node():
    """The graph must never reference a node it didn't create — that would be
    exactly the kind of unverifiable claim the evidence graph exists to prevent."""
    result = evaluate_exception(CASE_A["matching_input"], TOLERANCE)
    graph = build_evidence_graph("EXC-2026-0001", CASE_A["documents"], result, TOLERANCE)
    node_ids = {n.id for n in graph.nodes}
    for edge in graph.edges:
        assert edge.source in node_ids
        assert edge.target in node_ids


def test_extracted_values_only_cite_documents_they_came_from():
    """Provenance must be true, not merely present. The unit price is read
    from the purchase order and the invoice; claiming it also came from the
    goods receipt or the rejection notice is a false claim on the one screen
    a reviewer uses to check everything else."""
    result = evaluate_exception(CASE_A["matching_input"], TOLERANCE)
    graph = build_evidence_graph("EXC-2026-0001", CASE_A["documents"], result, TOLERANCE)

    node_type = {n.id: n.label for n in graph.nodes}
    cited = {
        node_type[e.target]
        for e in graph.edges
        if e.relationship == "extracted_from" and "value-unit_price" in e.source
    }
    assert cited == {"purchase_order_001.pdf", "vendor_invoice_001.pdf"}


def test_quantity_cites_the_goods_receipt_not_the_purchase_order():
    """Quantity is checked against what was RECEIVED, so the receipt is its
    authorising source — not the PO."""
    result = evaluate_exception(CASE_A["matching_input"], TOLERANCE)
    graph = build_evidence_graph("EXC-2026-0001", CASE_A["documents"], result, TOLERANCE)

    labels = {n.id: n.label for n in graph.nodes}
    cited = {
        labels[e.target]
        for e in graph.edges
        if e.relationship == "extracted_from" and "value-quantity" in e.source
    }
    assert cited == {"goods_receipt_note_001.pdf", "vendor_invoice_001.pdf"}
