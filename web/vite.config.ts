import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发期前端跑 5173，后端跑 8000。
// 用 proxy 而不是 CORS：WebSocket 也要转发，统一在一处配置更省心。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
});
