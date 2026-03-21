import { useState, useEffect, useCallback, useRef } from 'react'
import { authFetch } from '../hooks/useApi'

const STEPS = [
  {
    target: '[data-tour="sidebar-portfolio"]',
    title: 'Portfolio',
    text: 'Hier siehst du all deine Positionen, Allokationen und die Performance deines Portfolios.',
    position: 'right',
  },
  {
    target: '[data-tour="sidebar-watchlist"]',
    title: 'Watchlist',
    text: 'Analysiere Aktien mit dem 21-Punkte Setup-Score und finde die besten Einstiegspunkte.',
    position: 'right',
  },
  {
    target: '[data-tour="sidebar-market"]',
    title: 'Markt & Sektoren',
    text: 'Makro-Gate, VIX, Sektor-Rotation — alles auf einen Blick.',
    position: 'right',
  },
  {
    target: '[data-tour="sidebar-transactions"]',
    title: 'Transaktionen',
    text: 'Erfasse Trades manuell oder importiere sie bequem per CSV.',
    position: 'right',
  },
  {
    target: '[data-tour="sidebar-hilfe"]',
    title: 'Hilfe',
    text: 'Alle Funktionen erklärt. Unterstrichene Begriffe haben Tooltips!',
    position: 'right',
  },
  {
    target: '[data-tour="sidebar-ctrlk"]',
    title: 'Schnellsuche',
    text: 'Schnellsuche mit Cmd+K / Ctrl+K — finde Aktien, Seiten und Funktionen sofort.',
    position: 'right',
  },
  {
    target: null,
    title: "Los geht's!",
    text: 'Die Checkliste auf der Portfolio-Seite führt dich durch die ersten Schritte. Viel Erfolg!',
    position: 'center',
  },
]

export default function OnboardingTour({ onComplete }) {
  const [step, setStep] = useState(0)
  const [rect, setRect] = useState(null)

  const current = STEPS[step]

  const measureTarget = useCallback(() => {
    if (!current.target) {
      setRect(null)
      return
    }
    const el = document.querySelector(current.target)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      // Small delay after scroll to measure correctly
      requestAnimationFrame(() => {
        setRect(el.getBoundingClientRect())
      })
    } else {
      setRect(null)
    }
  }, [current.target])

  useEffect(() => {
    measureTarget()
    window.addEventListener('resize', measureTarget)
    return () => window.removeEventListener('resize', measureTarget)
  }, [measureTarget])

  const next = () => {
    if (step < STEPS.length - 1) {
      setStep(step + 1)
    } else {
      finish()
    }
  }

  const finish = async () => {
    try {
      await authFetch('/api/settings/onboarding/tour-complete', { method: 'POST' })
    } catch (e) {
      // ignore
    }
    onComplete()
  }

  const padding = 8
  const tooltipRef = useRef(null)
  const [tooltipPos, setTooltipPos] = useState(null)
  const [arrowSide, setArrowSide] = useState(null)

  // Measure tooltip after render and clamp to viewport
  useEffect(() => {
    if (current.position === 'center' || !rect) {
      setTooltipPos(null)
      setArrowSide(null)
      return
    }

    const EDGE = 16
    const GAP = 16
    const TOOLTIP_W = 320
    const vw = window.innerWidth
    const vh = window.innerHeight

    // Preferred: right of target, vertically centered
    let top = rect.top + rect.height / 2
    let left = rect.right + GAP
    let side = 'left'
    let centered = true

    // If tooltip goes off-screen right, position below target instead
    if (left + TOOLTIP_W > vw - EDGE) {
      top = rect.bottom + 12
      left = rect.left
      side = 'top'
      centered = false
    }

    // Measure actual tooltip height (use a frame so ref is populated)
    requestAnimationFrame(() => {
      const el = tooltipRef.current
      const tooltipH = el ? el.offsetHeight : 200

      // If vertically centered, adjust from center
      let finalTop = centered ? top - tooltipH / 2 : top

      // Clamp: bottom edge
      if (finalTop + tooltipH > vh - EDGE) {
        finalTop = vh - tooltipH - EDGE
      }
      // Clamp: top edge
      if (finalTop < EDGE) {
        finalTop = EDGE
      }
      // Clamp: right edge
      if (left + TOOLTIP_W > vw - EDGE) {
        left = vw - TOOLTIP_W - EDGE
      }
      // Clamp: left edge
      if (left < EDGE) {
        left = EDGE
      }

      setTooltipPos({ top: finalTop, left })
      setArrowSide(side)
    })
  }, [rect, step, current.position])

  // Build final tooltip style
  let tooltipStyle = {}
  if (current.position === 'center' || !rect) {
    tooltipStyle = {
      position: 'fixed',
      top: '50%',
      left: '50%',
      transform: 'translate(-50%, -50%)',
      zIndex: 10000,
    }
  } else if (tooltipPos) {
    tooltipStyle = {
      position: 'fixed',
      top: tooltipPos.top,
      left: tooltipPos.left,
      zIndex: 10000,
    }
  } else {
    // Initial render before measurement — off-screen to avoid flash
    tooltipStyle = {
      position: 'fixed',
      top: -9999,
      left: -9999,
      zIndex: 10000,
    }
  }

  return (
    <>
      {/* Click-to-dismiss backdrop (transparent) */}
      <div
        style={{ position: 'fixed', inset: 0, zIndex: 9997 }}
        onClick={finish}
      />

      {/* Overlay with spotlight cutout — single layer only */}
      {rect ? (
        <>
          {/* Spotlight box-shadow: creates dark overlay WITH a hole */}
          <div
            style={{
              position: 'fixed',
              top: rect.top - padding,
              left: rect.left - padding,
              width: rect.width + padding * 2,
              height: rect.height + padding * 2,
              zIndex: 9998,
              borderRadius: 12,
              boxShadow: '0 0 0 9999px rgba(0, 0, 0, 0.35)',
              pointerEvents: 'none',
              transition: 'top 0.3s ease, left 0.3s ease, width 0.3s ease, height 0.3s ease',
            }}
          />
          {/* Glowing border around target */}
          <div
            style={{
              position: 'fixed',
              top: rect.top - 4,
              left: rect.left - 4,
              width: rect.width + 8,
              height: rect.height + 8,
              zIndex: 9999,
              borderRadius: 8,
              border: '2px solid #3b82f6',
              boxShadow: '0 0 12px rgba(59, 130, 246, 0.5), 0 0 24px rgba(59, 130, 246, 0.2)',
              pointerEvents: 'none',
              animation: 'tour-pulse 2s ease-in-out infinite',
              transition: 'top 0.3s ease, left 0.3s ease, width 0.3s ease, height 0.3s ease',
            }}
          />
        </>
      ) : (
        /* No target (center step) — simple light overlay */
        <div
          style={{ position: 'fixed', inset: 0, zIndex: 9998, background: 'rgba(0, 0, 0, 0.35)', pointerEvents: 'none' }}
        />
      )}

      {/* Pulse animation */}
      <style>{`
        @keyframes tour-pulse {
          0%, 100% { box-shadow: 0 0 12px rgba(59, 130, 246, 0.5), 0 0 24px rgba(59, 130, 246, 0.2); }
          50% { box-shadow: 0 0 16px rgba(59, 130, 246, 0.7), 0 0 32px rgba(59, 130, 246, 0.3); }
        }
      `}</style>

      {/* Tooltip */}
      <div
        ref={tooltipRef}
        style={{ ...tooltipStyle, maxHeight: 'calc(100vh - 32px)', overflowY: 'auto' }}
        className="bg-card border border-border rounded-xl shadow-2xl max-w-xs w-80 relative"
      >
        {/* Arrow pointing to target */}
        {arrowSide === 'left' && rect && tooltipPos && (
          <div style={{
            position: 'absolute', left: -8,
            top: Math.max(16, Math.min(rect.top + rect.height / 2 - tooltipPos.top, (tooltipRef.current?.offsetHeight || 200) - 16)),
            width: 0, height: 0,
            borderTop: '8px solid transparent', borderBottom: '8px solid transparent',
            borderRight: '8px solid var(--color-card, #1e293b)',
          }} />
        )}
        {arrowSide === 'top' && (
          <div style={{
            position: 'absolute', top: -8, left: 20,
            width: 0, height: 0,
            borderLeft: '8px solid transparent', borderRight: '8px solid transparent',
            borderBottom: '8px solid var(--color-card, #1e293b)',
          }} />
        )}

        <div className="p-5">
          <h3 className="text-base font-semibold text-text-primary mb-2">{current.title}</h3>
          <p className="text-sm text-text-secondary leading-relaxed">{current.text}</p>
        </div>

        <div className="px-5 pb-4 flex items-center justify-between">
          {/* Step dots */}
          <div className="flex gap-1.5">
            {STEPS.map((_, i) => (
              <div
                key={i}
                className={`w-2 h-2 rounded-full transition-colors ${
                  i === step ? 'bg-primary' : i < step ? 'bg-primary/40' : 'bg-border'
                }`}
              />
            ))}
          </div>

          <div className="flex gap-2">
            {step < STEPS.length - 1 && (
              <button
                onClick={finish}
                className="px-3 py-1.5 text-xs text-text-muted hover:text-text-secondary transition-colors"
              >
                Überspringen
              </button>
            )}
            <button
              onClick={next}
              className="px-4 py-1.5 text-sm bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors font-medium"
            >
              {step < STEPS.length - 1 ? 'Weiter' : 'Starten'}
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
