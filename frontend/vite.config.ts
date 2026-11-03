import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * Backend address used by the dev and preview servers for `/api`.
 * Defaults to the local FastAPI server; `API_PROXY_TARGET` overrides it
 * (for example when the backend listens on another port).
 */
const apiTarget = process.env.API_PROXY_TARGET ?? "http://localhost:8000";

const proxy = {
  "/api": { target: apiTarget, changeOrigin: false },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy },
  preview: { port: 4173, proxy },
  build: {
    target: "es2022",
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
    unstubGlobals: true,
    // Leaves room above the 5 s asyncUtilTimeout set in src/test/setup.ts.
    testTimeout: 20000,
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "src/main.tsx", "src/vite-env.d.ts"],
      reporter: ["text", "html"],
    },
  },
});
