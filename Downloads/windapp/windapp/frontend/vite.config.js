import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Always target IPv4 explicitly: "localhost" can resolve to ::1 on Node >= 17 while uvicorn listens on 127.0.0.1.
const backend = { target: process.env.VITE_BACKEND || "http://127.0.0.1:8000", changeOrigin: true, secure: false };

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": backend, "/config": backend } },
});
