// useReveal.js — entrance animation that waits until the element is visible.
//
// Replaces `animation:rise-in ... both` on `.panel`, which had two faults:
// it re-ran on every route change (so a navigation looked like a page load),
// and it ran on paint rather than on visibility (so panels below the fold
// finished animating before anyone scrolled to them).
//
// The safety property that matters: the hidden state is applied by JS, not by
// CSS. `ref.current.classList.add("reveal")` happens in the same effect that
// creates the observer, so if this module never runs — JS disabled, a bundle
// error, an old browser — the content ships visible. A CSS rule that hides
// content while waiting for JS to reveal it is the standard way this pattern
// breaks, and it breaks silently.
import { useEffect, useRef } from "../lib.js";

function prefersReducedMotion() {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/**
 * Reveals a container's direct children as the container scrolls into view,
 * staggering them by their index.
 *
 * @param {object}  options
 * @param {string}  options.selector  which descendants to reveal. Defaults to
 *                                    direct children, which is what a grid or
 *                                    a stack of panels wants.
 * @param {number}  options.stagger   ms between siblings. 0 reveals together.
 * @param {number}  options.max       cap on the stagger index, so a 40-row
 *                                    table does not end with a 2.4s delay.
 * @param {string}  options.variant   "reveal" (rise) or "reveal-fade".
 * @param {Array}   options.deps      re-run when these change. REQUIRED
 *                                    whenever the container or its children
 *                                    are rendered conditionally — pass the
 *                                    data they are rendered from.
 *
 *                                    Without it the effect runs once, at
 *                                    mount, when a data-driven container has
 *                                    not been rendered yet: `ref.current` is
 *                                    null, the hook bails, and nothing is ever
 *                                    observed. It fails safe — no animation,
 *                                    never hidden content — but it fails
 *                                    silently, which is worse to find later.
 */
export function useReveal({
  selector = ":scope > *",
  stagger = 60,
  max = 8,
  variant = "reveal",
  deps = [],
} = {}) {
  const ref = useRef(null);

  useEffect(() => {
    const root = ref.current;
    if (!root) return undefined;

    let targets;
    try {
      targets = Array.from(root.querySelectorAll(selector));
    } catch {
      // A bad selector should degrade to "no animation", never to a crash
      // that takes the page with it.
      return undefined;
    }
    if (!targets.length) return undefined;

    // Reduced motion: nothing is hidden, nothing is observed.
    if (prefersReducedMotion() || typeof IntersectionObserver !== "function") {
      return undefined;
    }

    targets.forEach((el, i) => {
      el.style.setProperty("--i", String(Math.min(i, max)));
      el.classList.add(variant);
    });

    const reveal = (el) => {
      el.classList.add("is-in");
      observer.unobserve(el);
    };

    // Set as soon as the observer proves it is running at all. IntersectionObserver
    // invokes its callback once per target immediately after observe() — reporting
    // isIntersecting:false for anything off screen — so this flips to true even on
    // a long page where nothing has scrolled into view yet. It therefore
    // distinguishes "the observer works and is waiting" from "the observer is
    // never going to run", which is the distinction the deadline below needs.
    let observerRan = false;

    const observer = new IntersectionObserver(
      (entries) => {
        observerRan = true;
        for (const entry of entries) {
          if (entry.isIntersecting) reveal(entry.target);
        }
      },
      // A negative bottom margin means an element must be properly on screen,
      // not just clipping the edge, before it animates.
      { threshold: 0.05, rootMargin: "0px 0px -8% 0px" },
    );

    targets.forEach((el) => observer.observe(el));

    // Anything already on screen at mount is revealed on the next frame rather
    // than waiting for a scroll that may never come.
    const raf = requestAnimationFrame(() => {
      targets.forEach((el) => {
        const box = el.getBoundingClientRect();
        if (box.top < window.innerHeight && box.bottom > 0) reveal(el);
      });
    });

    // The deadline, and the reason it exists.
    //
    // Both mechanisms above are suspended in a tab the browser considers
    // hidden or throttled: requestAnimationFrame does not run, and the
    // observer's callback is deferred. In that state `.reveal` has already
    // been applied — so the content sits at opacity:0 with nothing scheduled
    // to bring it back. It self-heals when the tab is focused, but "invisible
    // until you click on it" is not a state an accounts-payable screen may
    // ever be in, and it also blanks the page for anything that renders
    // without a foreground tab: print, screenshotting, headless capture.
    //
    // setTimeout is throttled in background tabs but, unlike rAF, it still
    // fires. If the observer has not proved itself by then, this treats it as
    // unavailable and reveals everything at once — losing the stagger, which
    // is decoration, rather than the content, which is not.
    const deadline = setTimeout(() => {
      if (observerRan) return;
      targets.forEach((el) => el.classList.add("is-in"));
      observer.disconnect();
    }, 1500);

    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(deadline);
      observer.disconnect();
      // Leave the DOM as we found it. Without this, a component that
      // unmounts mid-animation and remounts keeps a stale hidden class.
      targets.forEach((el) => el.classList.remove(variant, "is-in"));
    };
    // `stagger` is read through the --i custom property rather than here, so
    // it is not a dependency; the rest re-runs the observer if they change.
    // The spread is intentional and is why callers must keep `deps` stable in
    // identity, not just in value — see the note on the parameter.
  }, [selector, max, variant, stagger, ...deps]);

  return ref;
}
