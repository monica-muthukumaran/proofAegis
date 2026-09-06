// Shared React runtime. Vite bundles these package imports for production.
import React from "react";
import ReactDOM from "react-dom/client";
import htm from "htm";

function createElement(type, props, ...children) {
  if (props) {
    const { class: className, for: htmlFor, autocomplete: autoComplete, "stroke-width": strokeWidth, "stroke-linecap": strokeLinecap, "stroke-linejoin": strokeLinejoin, ...rest } = props;
    props = {
      ...rest,
      ...(className !== undefined ? { className } : {}),
      ...(htmlFor !== undefined ? { htmlFor } : {}),
      ...(autoComplete !== undefined ? { autoComplete } : {}),
      ...(strokeWidth !== undefined ? { strokeWidth } : {}),
      ...(strokeLinecap !== undefined ? { strokeLinecap } : {}),
      ...(strokeLinejoin !== undefined ? { strokeLinejoin } : {}),
    };
  }
  return React.createElement(type, props, ...React.Children.toArray(children.flat(Infinity)));
}

export const html = htm.bind(createElement);
export const {
  useState, useEffect, useRef, useMemo, useCallback, useContext, createContext,
} = React;
export { React, ReactDOM };
