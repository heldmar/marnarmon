import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Static SPA. Runtime configuration is injected via /config.js (see
// public/config.js for dev, docker-entrypoint.sh for the container), NOT via
// build-time env, so one built image can target any host.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, host: true },
  build: { outDir: "dist", sourcemap: false },
});
