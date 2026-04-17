import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import packageJson from "./package.json";

// @ts-expect-error process is a nodejs global
const host = process.env.TAURI_DEV_HOST;

// https://vite.dev/config/
export default defineConfig(async () => ({
  plugins: [react()],
  define: {
    "import.meta.env.VITE_APP_VERSION": JSON.stringify(packageJson.version),
  },
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('@pixiv/three-vrm')) {
            return 'vrm-vendor';
          }
          if (id.includes('@react-three') || id.includes('/three/')) {
            return 'avatar-vendor';
          }
          if (id.includes('react-markdown') || id.includes('remark-gfm') || id.includes('rehype-highlight')) {
            return 'markdown-vendor';
          }
          if (id.includes('@tauri-apps')) {
            return 'tauri-vendor';
          }
          if (id.includes('/react/') || id.includes('react-dom') || id.includes('scheduler')) {
            return 'react-vendor';
          }
        },
      },
    },
  },

  // Vite options tailored for Tauri development and only applied in `tauri dev` or `tauri build`
  //
  // 1. prevent Vite from obscuring rust errors
  clearScreen: false,
  // 2. tauri expects a fixed port, fail if that port is not available
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 1421,
        }
      : undefined,
    watch: {
      // 3. tell Vite to ignore watching `src-tauri`
      ignored: ["**/src-tauri/**"],
    },
  },
}));
