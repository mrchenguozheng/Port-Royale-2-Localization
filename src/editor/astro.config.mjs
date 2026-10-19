import { defineConfig } from 'astro/config';

// 产物是纯静态文件，由后端的 FastAPI 直接托管 —— 前端不需要
// 自己的 Node 服务常驻。Astro 在这里只当构建工具。
export default defineConfig({
  outDir: './dist',
  // 开发时前端跑在 4321，接口在 8777；用代理把 /api 转过去，
  // 这样开发和生产的前端代码完全一致（都用同源 /api）。
  server: {
    port: 4321,
    proxy: {
      '/api': 'http://127.0.0.1:8777',
    },
  },
  devToolbar: { enabled: false },
});
