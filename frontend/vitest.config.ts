import { defineConfig } from "vitest/config";

export default defineConfig({
  // Components use the automatic JSX runtime (as Next.js compiles them), so
  // tests that render them don't need React in scope.
  esbuild: { jsx: "automatic" },
  test: {
    environment: "node",
    globals: true,
  },
});
