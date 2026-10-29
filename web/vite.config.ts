import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `npm run dev` serves the UI on :5173 with hot reload and forwards /api to the demo server on :8788
// (`fintrack-demo` in .claude/launch.json, made-up data from scripts/seed_demo.py). Development never
// talks to the production server on :8787, so real data can't show up in a dev session (see CLAUDE.md).
// `npm run build` writes dist/, which the Python server serves directly.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8788" },
  },
});
