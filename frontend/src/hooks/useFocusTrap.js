import { useEffect, useRef } from 'react'

/**
 * Focus trap hook for modals/dialogs.
 * Keeps Tab/Shift+Tab cycling within the container.
 * Auto-focuses the first focusable element on mount.
 */
export default function useFocusTrap(active = true) {
  const ref = useRef(null)

  useEffect(() => {
    if (!active || !ref.current) return

    const container = ref.current
    const focusable = () => container.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )

    // Focus first element
    const elements = focusable()
    if (elements.length > 0) {
      setTimeout(() => elements[0].focus(), 50)
    }

    const handleKeyDown = (e) => {
      if (e.key !== 'Tab') return
      const els = focusable()
      if (els.length === 0) return

      const first = els[0]
      const last = els[els.length - 1]

      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault()
          last.focus()
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }

    container.addEventListener('keydown', handleKeyDown)
    return () => container.removeEventListener('keydown', handleKeyDown)
  }, [active])

  return ref
}
