/// <reference types="vitest/config" />
// Sources:
// - https://tailwindcss.com/docs/installation/using-vite (Tailwind v4 @tailwindcss/vite plugin)
// - https://vite.dev/config/server-options#server-proxy (dev proxy for /api)
// - https://vitest.dev/config/ (test.environment, test.env)
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": "http://localhost:8000" } },
  test: {
    globals: true,
    environment: "jsdom",
    env: { VITE_MOCK: "1" },
    setupFiles: ["./src/test-setup.ts"],
  },
});
