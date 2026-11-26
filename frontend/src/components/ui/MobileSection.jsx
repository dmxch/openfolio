import { useEffect, useId, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'

/**
 * Aufklappbarer Abschnitt fuer Mobile-Seiten.
 *
 * Zweck: Mobil steht die kompakte Uebersicht oben; alles Weitere (Analyse-Karten,
 * Verwaltungs-Widgets) haengt darunter als Abschnitt. Die Kinder werden erst beim
 * ERSTEN Oeffnen gemountet (H11: fetchende Karten sollen auf dem Handy nicht
 * laden, solange niemand sie ansieht) und bleiben danach gemountet, damit ein
 * erneutes Aufklappen nicht neu laedt und Formular-Zustand erhalten bleibt.
 *
 * `hint` ist eine kurze Zusatzzeile unter dem Titel (z.B. Anzahl oder Summe).
 * `anchor` macht den Abschnitt per URL-Hash erreichbar: `#<anchor>` klappt ihn
 * auf und scrollt hin. Ohne das liefe ein Sprunglink (z.B. aus einem Alert) ins
 * Leere, weil das Ziel in einem geschlossenen Abschnitt noch gar nicht existiert.
 */
export default function MobileSection({ title, hint, anchor, defaultOpen = false, className = '', children }) {
  const [open, setOpen] = useState(defaultOpen)
  const [mounted, setMounted] = useState(defaultOpen)
  const panelId = useId()
  const rootRef = useRef(null)

  useEffect(() => {
    if (!anchor) return undefined
    const openIfTargeted = () => {
      if (window.location.hash !== `#${anchor}`) return
      setMounted(true)
      setOpen(true)
      rootRef.current?.scrollIntoView?.({ block: 'start' })
    }
    openIfTargeted()
    window.addEventListener('hashchange', openIfTargeted)
    return () => window.removeEventListener('hashchange', openIfTargeted)
  }, [anchor])

  const toggle = () => {
    setMounted(true)
    setOpen((v) => !v)
  }

  return (
    <section ref={rootRef} id={anchor} className={`scroll-mt-[72px] ${className}`}>
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        aria-controls={mounted ? panelId : undefined}
        className="w-full flex items-center gap-3 min-h-[48px] px-4 py-2.5 bg-card border border-border rounded-card text-left active:bg-hover transition-colors"
      >
        <span className="flex-1 min-w-0">
          <span className="block text-sm font-semibold text-text-primary truncate">{title}</span>
          {hint != null && hint !== '' && (
            <span className="block font-mono text-[11.5px] text-text-faint truncate mt-0.5">{hint}</span>
          )}
        </span>
        <ChevronDown
          size={16}
          className={`flex-none text-text-faint transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {mounted && (
        <div
          id={panelId}
          // Karten ohne Daten rendern oft nichts (null). Ein aufgeklappter, leerer
          // Abschnitt saehe aus wie ein Defekt — deshalb ein Hinweis per :empty.
          // Zugeklappt per Klasse `hidden`, nicht per hidden-Attribut: `.flex` hat die
          // gleiche Spezifitaet wie die Preflight-Regel fuer [hidden] und gewinnt.
          className={`${open ? 'flex' : 'hidden'} mt-2 flex-col gap-[14px] min-w-0 empty:before:content-['Noch_keine_Daten_vorhanden.'] empty:before:block empty:before:px-4 empty:before:py-3 empty:before:text-[12.5px] empty:before:text-text-muted`}
        >
          {children}
        </div>
      )}
    </section>
  )
}
