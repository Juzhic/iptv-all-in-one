import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { TDesignResolver } from 'unplugin-vue-components/resolvers'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

function loadBasicAuthConfig(env) {
  if (env.IPTV_AUTH_USERNAME || env.IPTV_AUTH_PASSWORD) {
    return {
      username: env.IPTV_AUTH_USERNAME || 'admin',
      password: env.IPTV_AUTH_PASSWORD || 'admin',
    }
  }

  try {
    const raw = JSON.parse(readFileSync(new URL('../basic_auth.json', import.meta.url), 'utf8'))
    return {
      username: raw.username,
      password: raw.password,
    }
  } catch (e) {
    console.warn('basic_auth.json not found and IPTV_AUTH_* is not set; using default development credentials')
    return {
      username: 'admin',
      password: 'admin',
    }
  }
}

export default defineConfig(({ command, mode }) => {
  const envDir = fileURLToPath(new URL('..', import.meta.url))
  const env = { ...loadEnv(mode, envDir, ''), ...process.env }
  const basicAuth = loadBasicAuthConfig(env)
  const basicAuthHeader = `Basic ${Buffer.from(`${basicAuth.username}:${basicAuth.password}`, 'utf8').toString('base64')}`
  const backendTarget = `http://127.0.0.1:${env.IPTV_PORT || 58080}`

  return {
  envDir,
  plugins: [
    vue(),
    Components({
      dts: false,
      resolvers: [TDesignResolver({ library: 'vue-next', esm: true })],
    }),
  ],
  base: command === 'serve' ? '/' : '/static/dist/',
  build: {
    outDir: '../dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const moduleId = id.replace(/\\/g, '/')
          if (!moduleId.includes('node_modules')) return undefined
          if (
            moduleId.includes('/node_modules/echarts/') ||
            moduleId.includes('/node_modules/zrender/') ||
            moduleId.includes('/node_modules/tslib/')
          ) return 'echarts'
          if (moduleId.includes('/node_modules/@vue/') || moduleId.includes('/node_modules/vue/')) return 'vue'
          return undefined
        },
      },
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
        configure(proxy) {
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.setHeader('Authorization', basicAuthHeader)
            proxyReq.setHeader('Origin', backendTarget)
          })
        },
      },
    },
  },
  css: {
    preprocessorOptions: {
      less: {
        javascriptEnabled: true,
        modifyVars: {},
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    restoreMocks: true,
    include: ['tests/**/*.spec.js'],
  },
  }
})
