import { html, useState, useEffect, useMemo, createPortal } from "../../lib.js";
import { TOUR_STEPS } from "./tourSteps.js";
import { Icon } from "../ui/primitives.js";

function useTargetRect(targetKey, stepIndex) {
  const [rect, setRect] = useState(null);

  useEffect(() => {
    if (!targetKey) { setRect(null); return; }
    let raf;
    const measure = () => {
      const el = document.querySelector(`[data-tour="${targetKey}"]`);
      if (el) {
        const r = el.getBoundingClientRect();
        setRect({ top: r.top, left: r.left, width: r.width, height: r.height });
      } else {
        setRect(null);
      }
    };
    // Allow the route/tab switch to render first, then measure (and re-measure
    // on resize/scroll so the tooltip never drifts off the real element).
    raf = requestAnimationFrame(() => requestAnimationFrame(measure));
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [targetKey, stepIndex]);

  return rect;
}

function positionTooltip(rect) {
  const margin = 16;
  const cardWidth = 360;
  const vw = window.innerWidth, vh = window.innerHeight;
  if (!rect) return { top: vh / 2 - 100, left: vw / 2 - cardWidth / 2 };

  const spaceRight = vw - (rect.left + rect.width);
  const spaceBelow = vh - (rect.top + rect.height);
  let top, left;

  if (spaceBelow > 220) {
    top = rect.top + rect.height + margin;
    left = Math.min(Math.max(rect.left, margin), vw - cardWidth - margin);
  } else if (spaceRight > cardWidth + margin) {
    top = Math.min(Math.max(rect.top, margin), vh - 260);
    left = rect.left + rect.width + margin;
  } else if (rect.left > cardWidth + margin) {
    top = Math.min(Math.max(rect.top, margin), vh - 260);
    left = rect.left - cardWidth - margin;
  } else {
    top = Math.max(rect.top - 220, margin);
    left = Math.min(Math.max(rect.left, margin), vw - cardWidth - margin);
  }
  // Mobile: always center-bottom for reliability.
  if (vw < 640) {
    top = vh - 280;
    left = (vw - Math.min(cardWidth, vw - 32)) / 2;
  }
  return { top, left };
}

export function GuidedTour({ stepIndex, onNext, onBack, onSkip, onClose, onRestart, onFinish, onGoToSignIn, onEnterRoute }) {
  const step = TOUR_STEPS[stepIndex];
  const rect = useTargetRect(step.target, stepIndex);
  const tooltipPos = useMemo(() => positionTooltip(rect), [rect]);

  useEffect(() => {
    onEnterRoute(step.route);
  }, [stepIndex]);

  useEffect(() => {
    const handleKey = (e) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight") onNext();
      else if (e.key === "ArrowLeft") onBack();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [stepIndex]);

  const progress = ((stepIndex + 1) / TOUR_STEPS.length) * 100;
  const isFirst = stepIndex === 0;
  const isLast = stepIndex === TOUR_STEPS.length - 1;

  if (step.isComplete) {
    return createPortal(html`
      <div class="tour-backdrop"></div>
      <div class="tour-center-card">
        <div class="stack gap-16" style=${{ alignItems: "center" }}>
          <div class="panel-elevated" style=${{ width: 52, height: 52, borderRadius: 999, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--verified)" }}>
            <${Icon} name="check" size=${24} />
          </div>
          <h3 class="text-section-title">${step.title}</h3>
          <p class="text-secondary">${step.description}</p>
          <div class="row gap-8" style=${{ flexWrap: "wrap", justifyContent: "center" }}>
            <button class="btn btn-primary" onClick=${onFinish}>Explore the application</button>
            <button class="btn btn-secondary" onClick=${onRestart}>Restart tour</button>
            <button class="btn btn-ghost" onClick=${onGoToSignIn}>Go to sign in</button>
          </div>
        </div>
      </div>
    `, document.body);
  }

  return createPortal(html`
    <div class="tour-backdrop" onClick=${onClose}></div>
    ${rect ? html`<div class="tour-highlight-box" style=${{ top: rect.top - 6, left: rect.left - 6, width: rect.width + 12, height: rect.height + 12 }}></div>` : null}
    <div class="tour-card" style=${{ top: tooltipPos.top, left: tooltipPos.left }} role="dialog" aria-live="polite">
      <div class="row" style=${{ justifyContent: "space-between", marginBottom: 10 }}>
        <span class="tour-step-counter">STEP ${stepIndex + 1} OF ${TOUR_STEPS.length}</span>
        <button class="btn btn-ghost btn-sm" onClick=${onClose} aria-label="Close tour" style=${{ padding: 4 }}>
          <${Icon} name="close" size=${15} />
        </button>
      </div>
      <div class="tour-progress-track"><div class="tour-progress-fill" style=${{ width: `${progress}%` }}></div></div>
      <div class="tour-card-title">${step.title}</div>
      <div class="tour-card-desc">${step.description}</div>
      ${step.facts ? html`
        <div class="panel-elevated stack gap-4" style=${{ padding: 12, marginBottom: 14 }}>
          ${step.facts.map((f, i) => html`<div key=${i} class="text-small">${f}</div>`)}
        </div>
      ` : null}
      <div class="row gap-8" style=${{ justifyContent: "space-between" }}>
        <button class="btn btn-ghost btn-sm" onClick=${onSkip}>Skip</button>
        <div class="row gap-8">
          ${!isFirst ? html`<button class="btn btn-secondary btn-sm" onClick=${onBack}><${Icon} name="arrowLeft" size=${13} /> Back<//>` : null}
          <button class="btn btn-primary btn-sm" onClick=${onNext}>
            ${isLast ? "Finish" : "Next"} <${Icon} name="arrowRight" size=${13} />
          </button>
        </div>
      </div>
    </div>
  `, document.body);
}

export { TOUR_STEPS };
