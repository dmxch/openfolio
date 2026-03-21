import { Component } from 'react'

export default class ErrorBoundary extends Component {
  state = { hasError: false, error: null }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, info) {
    console.error('ErrorBoundary caught:', error, info)

    // Auto-reload on stale chunk errors (after deployment with new hashes)
    const msg = error?.message || ''
    if (msg.includes('dynamically imported module') || msg.includes('Loading chunk') || msg.includes('Failed to fetch')) {
      const reloadKey = 'chunk_reload'
      if (!sessionStorage.getItem(reloadKey)) {
        sessionStorage.setItem(reloadKey, '1')
        window.location.reload()
        return
      }
      sessionStorage.removeItem(reloadKey)
    }

    // Fire-and-forget error report to backend
    try {
      fetch('/api/errors', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: error?.message || String(error),
          stack: error?.stack || null,
          componentStack: info?.componentStack || null,
          url: window.location.href,
          userAgent: navigator.userAgent,
          timestamp: new Date().toISOString(),
        }),
      }).catch(() => {})
    } catch {
      // Ignore — error reporting must never throw
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center min-h-screen bg-body text-text-primary">
          <h1 className="text-xl font-bold mb-2">Etwas ist schiefgelaufen</h1>
          <p className="text-text-muted mb-4">Die Anwendung hat einen Fehler festgestellt.</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
          >
            Seite neu laden
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
