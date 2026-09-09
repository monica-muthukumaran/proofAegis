// Shared React runtime. Vite bundles these package imports for production.
import React from "react";
import ReactDOM from "react-dom/client";
// createPortal lives in "react-dom", not "react-dom/client".
//
// Every fixed-position overlay in this app renders through it, and that is
// load-bearing rather than stylistic. `position: fixed` is only relative to
// the viewport while NO ancestor establishes a containing block for it, and
// this app has three ancestors that do:
//
//   .route-enter  animates `transform`, and any non-none transform makes the
//                 element the containing block for fixed descendants.
//   .sidebar      is `overflow-y: auto`; once an overlay is no longer truly
//                 viewport-fixed it is clipped by that scroll box.
//   .ambient      sets `isolation: isolate`, a stacking context.
//
// The symptom is not a crash. The overlay renders, sized to the whole
// scrollable page instead of the viewport, and centres itself far below the
// fold — so clicking the trigger looks like nothing happened. Portalling to
// document.body puts every overlay outside all three.
import { createPortal } from "react-dom";
import htm from "htm";

// HTML attribute names that React spells differently. These are irregular —
// they are not a hyphen-to-camelCase transform — so they need a table.
const RENAMED = {
  class: "className",
  for: "htmlFor",
  autocomplete: "autoComplete",
  crossorigin: "crossOrigin",
  tabindex: "tabIndex",
  readonly: "readOnly",
  maxlength: "maxLength",
  colspan: "colSpan",
  rowspan: "rowSpan",
};

// Everything else hyphenated — the whole SVG presentation-attribute surface —
// follows one rule: React wants it camelCased.
//
// This used to be a six-entry destructure listing stroke-width, stroke-linecap
// and stroke-linejoin by hand. Every other hyphenated SVG attribute was passed
// through untouched, and React DROPS an attribute it does not recognise after
// logging "Invalid DOM property" — silently, as far as the rendered output is
// concerned. That is why the evidence graph's arrowheads never appeared:
// `marker-end` was discarded on every edge, so the lines rendered without the
// markers that show which way the evidence flows.
//
// data-* and aria-* are the documented exceptions: React passes those through
// verbatim and camelCasing them would break them.
const PASS_THROUGH = /^(data|aria)-/;

function toReactProp(key) {
  if (RENAMED[key]) return RENAMED[key];
  if (!key.includes("-") || PASS_THROUGH.test(key)) return key;
  return key.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
}

function createElement(type, props, ...children) {
  if (props) {
    const mapped = {};
    for (const key in props) mapped[toReactProp(key)] = props[key];
    props = mapped;
  }
  return React.createElement(type, props, ...React.Children.toArray(children.flat(Infinity)));
}

export const html = htm.bind(createElement);
export const {
  useState, useEffect, useRef, useMemo, useCallback, useContext, createContext,
} = React;
export { React, ReactDOM, createPortal };
