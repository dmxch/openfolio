import { useEffect, useState } from 'react'

/**
 * Debounce-Hook: gibt den uebergebenen value erst nach `delay` ms ohne
 * Aenderung weiter. Verhindert API-Spam bei Slider-/Input-Aenderungen.
 *
 * @param {*} value beliebiger Input-Wert (string, number, object via JSON-stable-id)
 * @param {number} delay Verzoegerung in ms (Default 300)
 * @returns debounced value
 */
export default function useDebouncedValue(value, delay = 300) {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])

  return debounced
}
