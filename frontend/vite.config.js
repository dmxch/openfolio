import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync, copyFileSync, existsSync, mkdirSync } from 'fs'
import { resolve } from 'path'

// resolve() statt CWD-relativ: der Build darf nicht davon abhaengen, aus welchem
// Verzeichnis er gestartet wurde.
const pkg = JSON.parse(readFileSync(resolve(import.meta.dirname, 'package.json'), 'utf-8'))

function copyChangelog() {
  return {
    name: 'copy-changelog',
    buildStart() {
      const src = resolve(import.meta.dirname, '../CHANGELOG.md')
      const dest = resolve(import.meta.dirname, 'public/changelog.md')
      if (existsSync(src)) {
        if (!existsSync(resolve(import.meta.dirname, 'public'))) {
          mkdirSync(resolve(import.meta.dirname, 'public'))
        }
        copyFileSync(src, dest)
      }
    },
    configureServer(server) {
      server.middlewares.use('/changelog.md', (_req, res) => {
        const src = resolve(import.meta.dirname, '../CHANGELOG.md')
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
  build: {
    // BEWUSST gesetzt, nicht dem Default ueberlassen: Vite 8 hebt den Default-Target
    // von chrome87/safari14 auf chrome111/safari16.4 an. Das ist eine stille
    // Verengung der unterstuetzten Browser — der Build bleibt gruen, aeltere
    // Browser bekommen einfach eine weisse Seite. Hier steht die Support-Matrix,
    // die OpenFolio bis Vite 6 hatte; wer sie anheben will, tut das sichtbar.
    target: ['es2020', 'chrome87', 'edge88', 'firefox78', 'safari14'],
  },
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
