import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { NaiveUiResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig(({ mode }) => ({
  base: mode === 'production' ? '/new/' : '/',
  plugins: [
    vue(),
    AutoImport({
      imports: ['vue', 'vue-router', 'pinia'],
      dts: 'src/auto-imports.d.ts',
    }),
    Components({
      resolvers: [NaiveUiResolver()],
      dts: 'src/components.d.ts',
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      // 后端对 POST 校验 Origin == APP_BASE_URL；开发时浏览器来源是 5173，需改写为后端地址。
      '/api': {
        target: 'http://127.0.0.1:7188',
        headers: { Origin: 'http://localhost:7188' },
      },
    },
  },
}))
