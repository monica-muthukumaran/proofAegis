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
import "./theme-tokens.css";
import "./styles-color.css";

// Before render, so a dark-mode user never sees a white flash.
initTheme();

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(html`
  <${AuthProvider}>
    <${App} />
  <//>
`);
