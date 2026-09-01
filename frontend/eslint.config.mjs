import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      // This app's data comes from a REST API (lib/api.ts), not React
      // state managed elsewhere -- "fetch in a useEffect, setState with
      // the result" is exactly the pattern this rule's own docs call out
      // as fine ("calling setState in a callback function when external
      // state changes"), and it fires on every such effect across the
      // app (page loads, the command palette, shared-project state).
      // Kept as a warning rather than off: a genuinely synchronous,
      // no-external-source setState-in-effect (an actual smell) still
      // gets flagged, just doesn't fail the build.
      "react-hooks/set-state-in-effect": "warn",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
