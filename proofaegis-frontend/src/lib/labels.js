// labels.js — shared explanatory copy for terms the UI shows as bare numbers.
//
// "Match score: 80.7%" tells a first-time user nothing: they cannot tell what
// is being measured or whether 80 is good. The definition lives here once, so
// the queue header, the dashboard KPI, and the match workspace all explain it
// the same way and cannot drift into three different stories.
//
// The wording deliberately mirrors the formula in
// backend/services/matching_service.py — round(100 * matched / evaluable) —
// including the part people get wrong: a legitimately missing document does
// not drag the score down, because that is reported as its own finding.

export const MATCH_SCORE_HINT =
  "Share of comparable fields that matched or fell within tolerance. " +
  "Fields that could not be compared — because a document is missing — are " +
  "excluded rather than counted as failures; a missing document is reported " +
  "as its own finding. 100% means every field ProofAegis could check agreed.";

export const FINANCIAL_IMPACT_HINT =
  "Money at risk on this case, calculated in code — never by AI. For a price " +
  "or quantity variance it is the size of the gap; for a missing goods " +
  "receipt or purchase order it is the full invoice amount, because none of " +
  "it can be verified yet.";

export const TOLERANCE_HINT =
  "How far an invoice may differ from the purchase order before ProofAegis " +
  "raises an exception. Read from Firestore, applied by deterministic code.";

export const VALUE_ON_HOLD_HINT =
  "Total financial impact across every open exception — what is currently " +
  "blocked from payment pending review.";
