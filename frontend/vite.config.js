import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync, copyFileSync, existsSync, mkdirSync } from 'fs'
import { resolve } from 'path'

const pkg = JSON.parse(readFileSync('./package.json', 'utf-8'))

function copyChangelog() {
  return {
    name: 'copy-changelog',
    buildStart() {
      const src = resolve(__dirname, '../CHANGELOG.md')
      const dest = resolve(__dirname, 'public/changelog.md')
      if (existsSync(src)) {
        if (!existsSync(resolve(__dirname, 'public'))) {
          mkdirSync(resolve(__dirname, 'public'))
        }
        copyFileSync(src, dest)
      }
    },
    configureServer(server) {
      server.middlewares.use('/changelog.md', (_req, res) => {
        const src = resolve(__dirname, '../CHANGELOG.md')
        if (existsSync(src)) {
          res.setHeader('Content-Type', 'text/plain; charset=utf-8')
          res.end(readFileSync(src, 'utf-8'))
        } else {
          res.statusCode = 404
          res.end('Not found')
        }
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), copyChangelog()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.API_URL || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
  },
})
