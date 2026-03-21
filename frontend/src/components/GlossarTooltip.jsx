import { useState, useRef, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { lookupGlossary } from '../data/glossary'

export default function G({ term, children }) {
  const entry = lookupGlossary(term)
  const [show, setShow] = useState(false)
  const [style, setStyle] = useState(null)
  const triggerRef = useRef(null)
  const tooltipRef = useRef(null)
  const hideTimer = useRef(null)

  if (!entry) return children ?? term

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
    computePosition()
    setShow(true)
  }, [computePosition])

  const handleHide = useCallback(() => {
    hideTimer.current = setTimeout(() => setShow(false), 150)
  }, [])

  const handleTooltipEnter = useCallback(() => {
    clearTimeout(hideTimer.current)
  }, [])

  // Re-measure after tooltip renders (in case estimate was off)
  useEffect(() => {
    if (show && tooltipRef.current && triggerRef.current) {
      const tooltipRect = tooltipRef.current.getBoundingClientRect()
      // If tooltip overflows top of viewport, flip to below
      if (tooltipRect.top < 0) {
        const rect = triggerRef.current.getBoundingClientRect()
        setStyle(prev => prev ? { ...prev, top: rect.bottom + 8, transform: 'none' } : prev)
      }
    }
  }, [show])

  useEffect(() => () => clearTimeout(hideTimer.current), [])

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
      aria-describedby={show ? `glossar-${entry.key}` : undefined}
    >
      {children ?? term}
      {show && style && createPortal(
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
