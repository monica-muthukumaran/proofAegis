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
    },
  },
];
