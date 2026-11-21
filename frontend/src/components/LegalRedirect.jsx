import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { useLegalLinks } from '../lib/legalLinks'

const GITHUB_URL = 'https://github.com/dmxch/openfolio'

// Zeigt die Betreiber-URL auf dieselbe Origin und denselben Pfad wie diese Seite,
// wuerde replace() endlos neu laden.
function pointsToCurrentPage(url) {
  try {
    const target = new URL(url, window.location.href)
    const here = window.location
    const trim = (p) => p.replace(/\/+$/, '') || '/'
    return target.origin === here.origin && trim(target.pathname) === trim(here.pathname)
  } catch {
    return false
  }
}

// Alte Routen (/nutzungsbedingungen, /datenschutz, /impressum) bleiben fuer
// Lesezeichen und Links bestehen: mit konfigurierter Betreiber-URL wird
// weitergeleitet, sonst erscheint die neutrale Seite (fallback).
export default function LegalRedirect({ linkKey, fallback }) {
  const links = useLegalLinks()
  const url = links[linkKey]
  const [failed, setFailed] = useState(false)

  const loop = url ? pointsToCurrentPage(url) : false
  const redirect = !!url && !loop

  useEffect(() => {
    if (loop) {
      console.warn('LegalRedirect: configured URL points to the current page, not redirecting')
      return
    }
    if (!redirect) return
    try {
      window.location.replace(url)
    } catch (err) {
      console.warn('LegalRedirect: redirect failed', err)
      setFailed(true)
    }
  }, [url, loop, redirect])

  if (!links.loaded || (redirect && !failed)) return <div className="min-h-screen bg-body" />
  return fallback
}

export function NoTermsPage() {
  return (
    <div className="min-h-screen bg-body">
      <div className="max-w-[760px] mx-auto px-4 py-14 space-y-6">
        <h1 className="text-[22px] font-semibold tracking-[-0.01em] text-text-primary">Nutzungsbedingungen</h1>
        <div className="rounded-card border border-border bg-card p-[18px] text-sm text-text-secondary leading-relaxed space-y-2">
          <p>Der Betreiber dieser Instanz hat keine Nutzungsbedingungen hinterlegt. Für die Software OpenFolio gilt die MIT-Lizenz.</p>
          <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="text-link hover:underline inline-block">
            github.com/dmxch/openfolio
          </a>
        </div>
        <div className="text-xs pt-2 space-x-4">
          <Link to="/disclaimer" className="text-text-muted hover:text-text-primary transition-colors">Rechtlicher Hinweis</Link>
          <Link to="/datenschutz" className="text-text-muted hover:text-text-primary transition-colors">Datenschutz</Link>
          <Link to="/impressum" className="text-text-muted hover:text-text-primary transition-colors">Impressum</Link>
        </div>
      </div>
    </div>
  )
}
