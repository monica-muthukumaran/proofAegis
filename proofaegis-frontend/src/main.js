import { html, ReactDOM } from "./lib.js";
import { AuthProvider } from "./services/AuthContext.js";
import { App } from "./pages/App.js";
import { initTheme } from "./lib/theme.js";
import "../styles.css";
// Order matters, and it is the only thing keeping these three files free of
// !important:
//   styles.css        the original sheet — structure, layout, components
//   theme-tokens.css  replaces its palette and type, and corrects the places
//                     that hardcoded a colour before a theme existed
//   styles-color.css  the categorical colour system for the evidence graph,
//                     which sits ON TOP of the theme because its hues are
//                     identity rather than chrome and must survive a retheme
//   styles-brand.css  the brand hue, the type scale, and the imagery layer.
//                     Sits above the theme because it ADDS a colour rather
//                     than replacing one: --brand is chrome (the mark, focus,
//                     active nav, links) and never touches a status, which is
//                     what keeps theme-tokens' "rust means risk" rule intact.
//   styles-motion.css last, so its transitions win over the static
//                     declarations in the sheets above without !important
import "./theme-tokens.css";
import "./styles-color.css";
import "./styles-brand.css";
import "./styles-motion.css";

// Before render, so a dark-mode user never sees a white flash.
initTheme();

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(html`
  <${AuthProvider}>
    <${App} />
  <//>
`);
