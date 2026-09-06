// useCountUp.js — animates a number from 0 to its value on mount.
//
// A KPI that snaps into place reads as static markup; one that settles reads
// as a live figure someone just calculated. Cheap perceived-quality win, and
// the only motion in the app that touches actual data.
//
// Two rules it respects:
//   * prefers-reduced-motion is honoured — the value appears immediately.
//   * The animation is purely presentational. The underlying number is never
//     rounded, scaled, or altered; the final frame is always exactly the
//     value passed in, so nothing displayed can disagree with the API.
import { useState, useEffect, useRef } from "../lib.js";

const DEFAULT_DURATION = 750;

// Decelerating ease: fast start, soft landing.
const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

function prefersReducedMotion() {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

export function useCountUp(target, { duration = DEFAULT_DURATION } = {}) {
  const numeric = typeof target === "number" && Number.isFinite(target);
  const [display, setDisplay] = useState(numeric ? 0 : target);
  const frameRef = useRef(null);

  useEffect(() => {
    if (!numeric) {
      setDisplay(target);
      return undefined;
    }
    if (prefersReducedMotion() || target === 0) {
      setDisplay(target);
      return undefined;
    }

    const start = performance.now();
    const step = (now) => {
      const progress = Math.min(1, (now - start) / duration);
      // The last frame assigns the exact target rather than an eased
      // approximation of it — no KPI should ever settle on 24,999.7.
      setDisplay(progress >= 1 ? target : target * easeOutCubic(progress));
      if (progress < 1) frameRef.current = requestAnimationFrame(step);
    };
    frameRef.current = requestAnimationFrame(step);

    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
    };
  }, [target, duration, numeric]);

  return display;
}
