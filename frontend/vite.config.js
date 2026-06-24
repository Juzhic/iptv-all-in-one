import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { readFileSync } from 'node:fs'

function loadBasicAuthConfig() {
  try {
    const raw = JSON.parse(readFileSync(new URL('../basic_auth.json', import.meta.url), 'utf8'))
    return {
      username: raw.username,
      password: raw.password,
    }
  } catch (e) {
    console.warn('basic_auth.json not found, using default credentials')
    return {
      username: 'admin',
      password: 'admin',
    }
  }
}

const basicAuth = loadBasicAuthConfig()
const basicAuthHeader = `Basic ${Buffer.from(`${basicAuth.username}:${basicAuth.password}`, 'utf8').toString('base64')}`

export default defineConfig(({ command }) => ({
  plugins: [vue()],
  base: command === 'serve' ? '/' : '/static/dist/',
  build: {
    outDir: '../dist',
    emptyOutDir: true,
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${process.env.IPTV_PORT || 58080}`,
        changeOrigin: true,
        configure(proxy) {
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.setHeader('Authorization', basicAuthHeader)
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
}))
