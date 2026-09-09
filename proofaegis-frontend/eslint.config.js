export default [
  { ignores: ["dist/**", "node_modules/**"] },
  {
    files: ["src/**/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: { window: "readonly", document: "readonly", sessionStorage: "readonly", AbortSignal: "readonly", setTimeout: "readonly", fetch: "readonly", requestAnimationFrame: "readonly", cancelAnimationFrame: "readonly", clearTimeout: "readonly", IntersectionObserver: "readonly", matchMedia: "readonly", FormData: "readonly", XMLHttpRequest: "readonly", URL: "readonly", localStorage: "readonly", performance: "readonly", navigator: "readonly", KeyboardEvent: "readonly", Blob: "readonly", File: "readonly" },
    },
    rules: {
      "no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
      "no-undef": "error",
      // A duplicate key in an object literal is silently resolved by "last one
      // wins", so it never throws and never shows up in a diff review — it
      // just quietly changes behaviour. This shipped: ExceptionTable's
      // TYPE_TONE had duplicate_invoice listed twice, and the second entry
      // demoted the single most serious finding in accounts payable (paying
      // the same invoice twice) from `critical` to `exception`.
      "no-dupe-keys": "error",
      // Same family of silent-overwrite bug, one level up.
      "no-dupe-args": "error",
      "no-dupe-else-if": "error",
      "no-duplicate-case": "error",
      // Catches `if (x = 1)` and unreachable code after a return, both of
      // which read as correct and behave otherwise.
      "no-cond-assign": "error",
      "no-unreachable": "error",
      "no-self-compare": "error",
      "no-constant-condition": ["error", { checkLoops: false }],
    },
  },
];
