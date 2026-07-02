import { useState, useEffect } from 'react'

// Tailwind md-Breakpoint = 768px → mobile ist alles darunter. 767.98 statt
// 767: bei fraktionalen Viewport-Breiten (Zoom/DPR, z.B. 767.5px) würde sonst
// WEDER der JS-Mobile-Zweig (max-width 767 matcht nicht) NOCH der CSS-Desktop-
// Zweig (md = min-width 768 matcht nicht) greifen → leere Seite.
const MOBILE_QUERY = '(max-width: 767.98px)'

/**
 * Liefert true, wenn der Viewport unter dem Tailwind-md-Breakpoint liegt.
 *
 * Zweck (H11): Desktop- und Mobile-Baum nicht mehr gleichzeitig mounten
 * (CSS `hidden`/`md:hidden` versteckt nur — teure Kinder wie TradingView-Embeds
 * oder fetchende Panels laufen sonst doppelt). Pages rendern die Zweige damit
 * BEDINGT; die CSS-Klassen bleiben als Absicherung stehen.
 *
 * SSR-safe: ohne window/matchMedia (z.B. Tests) initial false, kein Zugriff
 * ausserhalb von useEffect noetig ausser dem lazy Initializer.
 */
export default function useIsMobile() {
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(MOBILE_QUERY).matches
      : false
  )

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined
    const mql = window.matchMedia(MOBILE_QUERY)
    const onChange = (e) => setIsMobile(e.matches)
    // Zustand syncen, falls sich der Viewport zwischen Initial-Render und
    // Effekt-Lauf geaendert hat.
    setIsMobile(mql.matches)
    if (typeof mql.addEventListener === 'function') {
      mql.addEventListener('change', onChange)
      return () => mql.removeEventListener('change', onChange)
    }
    // Fallback fuer aeltere Safari-Versionen (< 14)
    mql.addListener(onChange)
    return () => mql.removeListener(onChange)
  }, [])

  return isMobile
}
