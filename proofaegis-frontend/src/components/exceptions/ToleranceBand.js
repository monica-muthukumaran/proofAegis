// ToleranceBand.js — the variance, drawn to scale.
//
// "10.42% variance, outside the 5% tolerance" is a sentence a reviewer has to
// parse. This is the same fact as a picture: the expected value at centre, the
// allowed band shaded around it, and a marker showing where the invoice
// actually landed. Whether the marker sits inside or outside the band is
// readable in about half a second, without reading any number at all.
//
// Every value comes from the deterministic Comparison the matcher produced —
// this draws what was computed, it never recomputes anything.
import { html } from "../../lib.js";

const FIELD_LABEL = {
  vendor: "Vendor", po_number: "PO number", quantity: "Quantity",
  unit_price: "Unit price", tax: "Tax", total: "Total",
};

const SOURCE_LABEL = {
  quantity: "goods receipt",
  unit_price: "purchase order",
  total: "purchase order",
  tax: "purchase order",
};

function formatNumber(value) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

/**
 * One comparison, drawn as a band.
 *
 * The horizontal axis is centred on the expected value. Its half-width is
 * whichever is larger — the tolerance, or the actual variance plus headroom —
 * so an outside-tolerance marker is always visible on the canvas rather than
 * clipped off the end, while an inside-tolerance one still shows the band
 * filling most of the width.
 */
function Band({ comparison }) {
  const { expected_value: expected, actual_value: actual,
          percentage_variance: variance, tolerance_percent: tolerance } = comparison;

  if (expected === null || expected === undefined || actual === null || actual === undefined) return null;
  if (tolerance === null || tolerance === undefined || variance === null || variance === undefined) return null;

  const outside = comparison.classification === "outside_tolerance";
  // Axis half-width in percentage points, with 40% headroom past the marker.
  const axisSpan = Math.max(tolerance * 2, Math.abs(variance) * 1.4, 1);
  const toPercent = (pct) => 50 + (pct / axisSpan) * 50;

  const bandLeft = toPercent(-tolerance);
  const bandRight = toPercent(tolerance);
  const markerX = Math.max(1.5, Math.min(98.5, toPercent(variance)));

  const expectedNum = Number(expected);
  const lowerBound = Number.isNaN(expectedNum) ? null : expectedNum * (1 - tolerance / 100);
  const upperBound = Number.isNaN(expectedNum) ? null : expectedNum * (1 + tolerance / 100);

  return html`
    <div class="stack gap-8 tolerance-band">
      <div class="row" style=${{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <span style=${{ fontWeight: 600 }}>${FIELD_LABEL[comparison.field] || comparison.field}</span>
        <span class="text-muted text-small">
          ${variance > 0 ? "+" : ""}${variance}% against a ±${tolerance}% tolerance
        </span>
      </div>

      <div class="tolerance-track" role="img"
        aria-label=${`${FIELD_LABEL[comparison.field] || comparison.field}: expected ${formatNumber(expected)}, actual ${formatNumber(actual)}, variance ${variance} percent against a ${tolerance} percent tolerance, ${outside ? "outside" : "within"} tolerance`}>
        <div class="tolerance-allowed"
          style=${{ left: `${bandLeft}%`, width: `${bandRight - bandLeft}%` }}></div>
        <div class="tolerance-center" style=${{ left: "50%" }}></div>
        <div class="tolerance-marker ${outside ? "outside" : "inside"}"
          style=${{ left: `${markerX}%` }}></div>
      </div>

      <div class="row tolerance-scale" style=${{ justifyContent: "space-between" }}>
        <span class="text-muted text-small">
          ${lowerBound !== null ? formatNumber(lowerBound) : `−${tolerance}%`}
        </span>
        <span class="text-small" style=${{ fontWeight: 600 }}>
          ${formatNumber(expected)}
          <span class="text-muted"> (${SOURCE_LABEL[comparison.field] || "expected"})</span>
        </span>
        <span class="text-muted text-small">
          ${upperBound !== null ? formatNumber(upperBound) : `+${tolerance}%`}
        </span>
      </div>

      <div class="row gap-8" style=${{ flexWrap: "wrap" }}>
        <span class="text-small" style=${{ color: outside ? "var(--exception)" : "var(--verified)", fontWeight: 700 }}>
          Invoice: ${formatNumber(actual)}
        </span>
        <span class="text-muted text-small">
          ${outside
            ? `outside the allowed band — this is what raised the exception`
            : `inside the allowed band — no exception from this field`}
        </span>
      </div>
    </div>
  `;
}

export function ToleranceBand({ matchResult }) {
  // Only fields with a real numeric tolerance can be drawn this way. Vendor
  // and PO number are exact matches with no band to speak of, and a missing
  // document has nothing to plot — both are covered by the table below.
  const plottable = (matchResult.comparisons || []).filter((c) =>
    c.evaluable &&
    c.tolerance_percent !== null && c.tolerance_percent !== undefined &&
    c.percentage_variance !== null && c.percentage_variance !== undefined &&
    typeof c.expected_value === "number" && typeof c.actual_value === "number"
  );

  if (plottable.length === 0) return null;

  // Whatever drove the exception goes first; a reviewer should not have to
  // hunt for the row that matters.
  const ordered = [...plottable].sort((a, b) => {
    const aOut = a.classification === "outside_tolerance" ? 0 : 1;
    const bOut = b.classification === "outside_tolerance" ? 0 : 1;
    if (aOut !== bOut) return aOut - bOut;
    return Math.abs(b.percentage_variance) - Math.abs(a.percentage_variance);
  });

  return html`
    <div class="panel-elevated stack gap-20" style=${{ padding: 20 }}>
      <div class="stack gap-2">
        <span class="text-section-title" style=${{ fontSize: 15 }}>Tolerance check</span>
        <span class="text-muted text-small">
          Each field plotted against the band it was allowed to fall within. Drawn from the computed
          comparison — the shaded zone is the configured tolerance, the marker is the invoice.
        </span>
      </div>
      ${ordered.map((c) => html`<${Band} key=${c.field} comparison=${c} />`)}
    </div>
  `;
}
