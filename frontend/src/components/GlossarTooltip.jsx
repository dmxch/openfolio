import { useState, useRef, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'

// glossary.js (~72KB) lazy laden, damit es nicht am eager geladenen Dashboard
// im Initial-Chunk haengt. Modul-Level-Cache: nach dem ersten Laden loest jeder
// weitere Hover synchron auf (kein Flackern).
let glossaryModule = null
let glossaryPromise = null
function loadGlossaryModule() {
  if (glossaryModule) return Promise.resolve(glossaryModule)
  if (!glossaryPromise) {
    glossaryPromise = import('../data/glossary')
      .then((m) => {
        glossaryModule = m
        return m
      })
      .catch((err) => {
        // Fehlgeschlagenen Load (offline, stale Chunk nach Redeploy) NICHT
        // dauerhaft cachen — der nächste Hover versucht es erneut.
        glossaryPromise = null
        console.warn('Glossar-Chunk konnte nicht geladen werden:', err)
        return null
      })
  }
  return glossaryPromise
}

export default function G({ term, children }) {
  const [show, setShow] = useState(false)
  const [style, setStyle] = useState(null)
  // Render-Trigger, sobald das lazy geladene Glossar bereit ist.
  const [, setGlossaryTick] = useState(0)
  const triggerRef = useRef(null)
  const tooltipRef = useRef(null)
  const hideTimer = useRef(null)

  const entry = glossaryModule ? glossaryModule.lookupGlossary(term) : null

  const computePosition = useCallback(() => {
    if (!triggerRef.current) return
    const rect = triggerRef.current.getBoundingClientRect()
    const tooltipW = 320
    const gap = 8

    // Horizontal: center on trigger, clamp to viewport
    let left = rect.left + rect.width / 2 - tooltipW / 2
    left = Math.max(gap, Math.min(left, window.innerWidth - tooltipW - gap))

    // Vertical: prefer above trigger
    const above = rect.top > 120
    const top = above ? rect.top - gap : rect.bottom + gap
    const transform = above ? 'translateY(-100%)' : 'none'

    setStyle({ position: 'fixed', top, left, transform, width: tooltipW, zIndex: 9999 })
  }, [])

  const handleShow = useCallback(() => {
    clearTimeout(hideTimer.current)
    if (!glossaryModule) {
      loadGlossaryModule().then(() => setGlossaryTick((n) => n + 1))
    }
    computePosition()
    setShow(true)
  }, [computePosition])

  const handleHide = useCallback(() => {
    hideTimer.current = setTimeout(() => setShow(false), 150)
  }, [])

  const handleTooltipEnter = useCallback(() => {
    clearTimeout(hideTimer.current)
  }, [])

  // Re-measure after tooltip renders (in case estimate was off).
  // !!entry als Dep: nach dem Lazy-Load erscheint der Tooltip erst, wenn entry
  // aufloest — dann erneut messen.
  const hasEntry = !!entry
  useEffect(() => {
    if (show && tooltipRef.current && triggerRef.current) {
      const tooltipRect = tooltipRef.current.getBoundingClientRect()
      // If tooltip overflows top of viewport, flip to below
      if (tooltipRect.top < 0) {
        const rect = triggerRef.current.getBoundingClientRect()
        setStyle(prev => prev ? { ...prev, top: rect.bottom + 8, transform: 'none' } : prev)
      }
    }
  }, [show, hasEntry])

  useEffect(() => () => clearTimeout(hideTimer.current), [])

  // Erst NACH den Hooks (Hook-Reihenfolge muss stabil bleiben, entry kippt
  // nach dem Lazy-Load von null auf definiert). Solange das Glossar noch nicht
  // geladen ist, optimistisch den Trigger rendern (Fallback: kein Tooltip).
  if (glossaryModule && !entry) return children ?? term

  return (
    <span
      ref={triggerRef}
      className="inline cursor-help border-b border-dotted border-text-muted/40"
      onMouseEnter={handleShow}
      onMouseLeave={handleHide}
      onFocus={handleShow}
      onBlur={handleHide}
      tabIndex={0}
      role="button"
      aria-describedby={show && entry ? `glossar-${entry.key}` : undefined}
    >
      {children ?? term}
      {show && style && entry && createPortal(
        <div
          ref={tooltipRef}
          id={`glossar-${entry.key}`}
          role="tooltip"
          onMouseEnter={handleTooltipEnter}
          onMouseLeave={handleHide}
          className="max-w-[calc(100vw-16px)] px-3 py-2.5 rounded-lg border border-border bg-card shadow-2xl text-xs leading-relaxed text-text-secondary pointer-events-auto"
          style={style}
        >
          <span className="font-medium text-text-primary block mb-0.5">{entry.key}</span>
          <span>{entry.short}</span>
        </div>,
        document.body
      )}
    </span>
  )
}
