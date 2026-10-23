import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// 站点跑在 5000（run.py 的 ZHUIJU_PORT 默认值）。dev 时把接口与图片代理都转过去，
// 这样 `npm run dev` 打开 5173 就是真数据，不用改前端代码里的相对路径。
const BACKEND = `http://127.0.0.1:${process.env.ZHUIJU_PORT || 5000}`;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/static/spa/",
  build: {
    outDir: "../zhuiju/static/spa",
    emptyOutDir: true,
    sourcemap: false,
    // 前台只有一个入口，样式也只要一份：产物名固定成 app.js / app.css，
    // Jinja 壳里就能写死 /static/spa/app.js?v=…，不必读 manifest。
    cssCodeSplit: false,
    rollupOptions: {
      // 两个入口两个壳：前台 /、后台 /admin。产物名跟着入口名走（app.js / admin.js），
      // 样式两边共用同一份 app.css（cssCodeSplit=false），壳里各自引一次。
      input: { app: "src/main.tsx", admin: "src/admin.tsx" },
      output: {
        entryFileNames: "[name].js",
        chunkFileNames: "c-[name].js",
        assetFileNames: ({ names }) =>
          names[0]?.endsWith(".css") ? "app.css" : "assets/[name]-[hash][extname]",
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: BACKEND },
      "/img": { target: BACKEND },
      "/s": { target: BACKEND },
      "/admin": { target: BACKEND },
    },
  },
});
