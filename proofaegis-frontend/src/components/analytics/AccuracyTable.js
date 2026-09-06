import { html, useState, useEffect } from "../../lib.js";
import * as api from "../../services/api.js";
import { Badge, Icon } from "../ui/primitives.js";

// The slide. 320 cases, every exception type, precision and recall per type,
// and every disagreement named.
//
// The numbers come from `python -m eval.run_eval` and `python -m
// eval.extraction_eval`, written to disk and served from there. That
// indirection is deliberate: a screen that computed its own score on request
// would be the system grading itself, and the whole value of an eval is that
// somebody else can run the command and get the same answer.
//
// TWO THINGS THIS COMPONENT REFUSES TO DO
//
// It does not average the two harnesses into one number. Extraction failures
// and reasoning failures have different fixes, and a combined figure hides
// which one happened.
//
// It does not hide a clean result behind a clean result. Where the score is
// 1.000 the copy says what that does and does not mean, and the limitations
// the harness itself records are printed rather than summarised away. A
// perfect number with no scope attached is the least believable thing on a
// slide.

function pct(value) {
  return value == null ? "—" : value.toFixed(3);
}

function toneFor(value) {
  if (value == null) return "";
  if (value >= 0.95) return "";
  if (value >= 0.85) return "warn";
  return "bad";
}

export function AccuracyTable() {
  const [reports, setReports] = useState(null);
  const [notMeasured, setNotMeasured] = useState(null);

  useEffect(() => {
    api.getAccuracy().then((r) => {
      if (r.source === "error") { setNotMeasured(r.error); return; }
      setReports(r.data);
    });
  }, []);

  if (notMeasured) {
    return html`
      <div class="panel stack gap-8" style=${{ padding: 22 }}>
        <h3 class="text-section-title">Measured accuracy</h3>
        <p class="text-muted text-small">
          No eval run has been recorded. From the backend directory:
          <code>python -m eval.run_eval --count 320 --json data/generated/eval_report.json</code>
        </p>
      </div>`;
  }
  if (!reports) return null;

  const pipeline = reports.pipeline;
  const extraction = reports.extraction;

  return html`
    <div class="panel stack gap-20" style=${{ padding: 22 }} data-tour="accuracy">
      <div class="stack gap-2">
        <div class="row gap-8" style=${{ justifyContent: "space-between", flexWrap: "wrap" }}>
          <h3 class="text-section-title">Measured accuracy</h3>
          <${Badge} tone="verified">reproducible — one command<//>
        </div>
        <p class="text-muted text-small">
          Scored against a labelled portfolio where ground truth is the defect that was injected,
          labelled from the documented policy rather than from the matcher — so a disagreement
          between the two is a real result and not a tautology.
        </p>
      </div>

      ${pipeline ? html`
        <div class="stack gap-12">
          <div class="row gap-24" style=${{ flexWrap: "wrap" }}>
            <div class="stack gap-2">
              <span class="text-muted text-small">Cases scored</span>
              <span class="text-kpi num">${pipeline.cases}</span>
            </div>
            <div class="stack gap-2">
              <span class="text-muted text-small">Exception types</span>
              <span class="text-kpi num">${pipeline.exception_types}</span>
            </div>
            <div class="stack gap-2">
              <span class="text-muted text-small">Detection recall</span>
              <span class="text-kpi num">${pct(pipeline.detection.recall)}</span>
            </div>
            <div class="stack gap-2">
              <span class="text-muted text-small">Detection precision</span>
              <span class="text-kpi num">${pct(pipeline.detection.precision)}</span>
            </div>
            <div class="stack gap-2">
              <span class="text-muted text-small">Exact-type accuracy</span>
              <span class="text-kpi num">${pct(pipeline.exact_type_accuracy)}</span>
            </div>
          </div>

          <div class="table-scroll" role="region" aria-label="Per-type accuracy" tabIndex="0">
            <table>
              <thead><tr>
                <th>Exception type</th><th>Support</th><th>Precision</th>
                <th>Recall</th><th>F1</th><th>Missed</th><th>False alarms</th>
              </tr></thead>
              <tbody>
                ${Object.entries(pipeline.per_type)
                  .sort((a, b) => b[1].support - a[1].support)
                  .map(([type, stats]) => html`
                    <tr key=${type}>
                      <td style=${{ fontWeight: 600 }}>
                        <span class=${`type-dot ${type === "no_exception" ? "type-dot-clean" : "type-dot-single"}`}></span>
                        ${type.replaceAll("_", " ")}
                      </td>
                      <td class="num">${stats.support}</td>
                      <td>
                        <div class="row gap-8">
                          <span class="num" style=${{ minWidth: 42 }}>${pct(stats.precision)}</span>
                          <span class="metric-bar" style=${{ flex: 1 }}>
                            <span class=${`metric-bar-fill ${toneFor(stats.precision)}`}
                              style=${{ width: `${(stats.precision || 0) * 100}%` }}></span>
                          </span>
                        </div>
                      </td>
                      <td>
                        <div class="row gap-8">
                          <span class="num" style=${{ minWidth: 42 }}>${pct(stats.recall)}</span>
                          <span class="metric-bar" style=${{ flex: 1 }}>
                            <span class=${`metric-bar-fill ${toneFor(stats.recall)}`}
                              style=${{ width: `${(stats.recall || 0) * 100}%` }}></span>
                          </span>
                        </div>
                      </td>
                      <td class="num">${pct(stats.f1)}</td>
                      <td class="num">${stats.false_negative}</td>
                      <td class="num">${stats.false_positive}</td>
                    </tr>
                  `)}
              </tbody>
            </table>
          </div>

          ${pipeline.by_condition && pipeline.by_condition.degraded ? html`
            <div class="row gap-24" style=${{ flexWrap: "wrap" }}>
              <span class="text-small">
                <strong>On clean documents:</strong>
                ${" "}${pct(pipeline.by_condition.clean.exact_type_accuracy)}
                ${" "}(${pipeline.by_condition.clean.cases} cases)
              </span>
              <span class="text-small">
                <strong>On degraded documents:</strong>
                ${" "}${pct(pipeline.by_condition.degraded.exact_type_accuracy)}
                ${" "}(${pipeline.by_condition.degraded.cases} cases — vendor name spelled
                differently, tax basis mismatched, itemized with no scalar quantity,
                unreadable dates)
              </span>
            </div>` : null}

          ${(pipeline.misses || []).length ? html`
            <div class="stack gap-8">
              <span style=${{ fontWeight: 700 }}>
                Every disagreement, named (${pipeline.misses.length})
              </span>
              ${pipeline.misses.map((row) => html`
                <div key=${row.case_id} class="panel-elevated stack gap-2"
                  style=${{ padding: 12, borderLeft: "3px solid var(--exception)" }}>
                  <span class="text-small">
                    <strong class="id">${row.case_id}</strong> — expected ${row.expected.replaceAll("_", " ")},
                    got ${row.predicted.replaceAll("_", " ")}
                    ${row.noise !== "none" ? html`<span class="text-muted"> · ${row.noise.replaceAll("_", " ")}</span>` : null}
                  </span>
                  <span class="text-muted text-small">${row.expected_because}</span>
                </div>
              `)}
            </div>
          ` : html`
            <div class="row gap-8" style=${{ alignItems: "flex-start" }}>
              <${Icon} name="shield" size=${15} />
              <span class="text-secondary" style=${{ fontSize: 14 }}>
                No disagreements on this run. That is a claim about a decision layer given clean
                field values, which is arithmetic — it is not a claim about reading real
                documents. Earlier runs of this same harness found five defects that are now
                fixed: a false vendor mismatch on every spelling variant, a quantity check that
                silently skipped itemized invoices, a bank change masked by a near-duplicate, an
                unrecognised receipt-number label, and a parser returning a document's own title
                as its supplier.
              </span>
            </div>
          `}
        </div>` : null}

      ${extraction ? html`
        <div class="stack gap-10" style=${{ borderTop: "1px solid var(--line)", paddingTop: 18 }}>
          <span style=${{ fontWeight: 700 }}>Field extraction, across document layouts</span>
          <div class="row gap-24" style=${{ flexWrap: "wrap" }}>
            <div class="stack gap-2">
              <span class="text-muted text-small">Layouts</span>
              <span class="text-kpi num">${extraction.layouts}</span>
            </div>
            <div class="stack gap-2">
              <span class="text-muted text-small">Field comparisons</span>
              <span class="text-kpi num">${extraction.overall.scored}</span>
            </div>
            <div class="stack gap-2">
              <span class="text-muted text-small">Accuracy</span>
              <span class="text-kpi num">${pct(extraction.overall.accuracy)}</span>
            </div>
            <div class="stack gap-2">
              <span class="text-muted text-small">On unseen layouts</span>
              <span class="text-kpi num">${pct(extraction.unseen_layouts.accuracy)}</span>
            </div>
            <div class="stack gap-2">
              <span class="text-muted text-small">Wrong values</span>
              <span class="text-kpi num">${extraction.overall.wrong}</span>
            </div>
          </div>
          <p class="text-muted text-small" style=${{ margin: 0 }}>
            A <em>missed</em> field is reported as "not stated" and never compared; a
            <em>wrong</em> field would flow into a variance. They are counted apart because one
            is a gap and the other is a lie.
          </p>
          ${(extraction.limitations || []).length ? html`
            <p class="text-muted text-small" style=${{ margin: 0 }}>
              ${extraction.limitations.join(" ")}
            </p>` : null}
        </div>` : null}
    </div>
  `;
}
