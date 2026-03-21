import { useState, useRef, useCallback } from 'react'
import { Calendar } from 'lucide-react'

/**
 * Swiss date input (DD.MM.YYYY) with auto-formatting.
 *
 * Props:
 *   value    — ISO date string "YYYY-MM-DD" (internal format)
 *   onChange — called with ISO date string on valid input
 *   className, required, placeholder, ...rest
 */
export default function DateInput({ id, value, onChange, className = '', required, ...rest }) {
  // Convert ISO → display
  const isoToDisplay = (iso) => {
    if (!iso) return ''
    const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})/)
    return m ? `${m[3]}.${m[2]}.${m[1]}` : iso
  }

  // Convert display → ISO
  const displayToIso = (display) => {
    const m = display.match(/^(\d{2})\.(\d{2})\.(\d{4})$/)
    return m ? `${m[3]}-${m[2]}-${m[1]}` : null
  }

  const [text, setText] = useState(isoToDisplay(value))
  const [showCal, setShowCal] = useState(false)
  const ref = useRef()
  const calRef = useRef()

  // Sync when parent value changes
  const displayed = isoToDisplay(value)
  if (displayed && displayed !== text && document.activeElement !== ref.current) {
    // Only sync if not currently editing
  }

  const handleInput = useCallback((e) => {
    let raw = e.target.value.replace(/[^\d.]/g, '')

    // Auto-insert dots after DD and MM
    const digits = raw.replace(/\./g, '')
    if (digits.length >= 4) {
      raw = digits.slice(0, 2) + '.' + digits.slice(2, 4) + '.' + digits.slice(4, 8)
    } else if (digits.length >= 2) {
      raw = digits.slice(0, 2) + '.' + digits.slice(2)
    }

    if (raw.length > 10) raw = raw.slice(0, 10)
    setText(raw)

    // Try to parse complete date
    const iso = displayToIso(raw)
    if (iso) {
      // Validate it's a real date
      const d = new Date(iso)
      if (!isNaN(d.getTime())) {
        onChange(iso)
      }
    }
  }, [onChange])

  const handleBlur = useCallback(() => {
    // On blur, reformat to match current value
    setTimeout(() => {
      if (!calRef.current?.contains(document.activeElement)) {
        setShowCal(false)
      }
    }, 200)
    const iso = displayToIso(text)
    if (iso) {
      const d = new Date(iso)
      if (!isNaN(d.getTime())) {
        onChange(iso)
        setText(isoToDisplay(iso))
      }
    } else if (value) {
      setText(isoToDisplay(value))
    }
  }, [text, value, onChange])

  const handleCalSelect = useCallback((isoDate) => {
    onChange(isoDate)
    setText(isoToDisplay(isoDate))
    setShowCal(false)
  }, [onChange])

  return (
    <div className="relative">
      <input
        id={id}
        ref={ref}
        type="text"
        inputMode="numeric"
        placeholder="TT.MM.JJJJ"
        value={text}
        onChange={handleInput}
        onFocus={() => { setText(isoToDisplay(value)); setShowCal(false) }}
        onBlur={handleBlur}
        className={className}
        required={required}
        maxLength={10}
        {...rest}
      />
      <button
        type="button"
        tabIndex={-1}
        onClick={() => setShowCal(!showCal)}
        className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-primary transition-colors"
      >
        <Calendar size={14} />
      </button>
      {showCal && (
        <MiniCalendar
          ref={calRef}
          value={value}
          onSelect={handleCalSelect}
          onClose={() => setShowCal(false)}
        />
      )}
    </div>
  )
}

import { forwardRef, useMemo } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'

const MiniCalendar = forwardRef(function MiniCalendar({ value, onSelect, onClose }, ref) {
  const today = new Date()
  const selected = value ? new Date(value + 'T00:00:00') : today

  const [viewState, setViewState] = useState({
    year: selected.getFullYear(),
    month: selected.getMonth(),
  })

  const days = useMemo(() => {
    const y = viewState.year
    const m = viewState.month
    const firstDay = new Date(y, m, 1)
    const lastDay = new Date(y, m + 1, 0)
    const startPad = (firstDay.getDay() + 6) % 7 // Monday = 0
    const result = []
    // Padding
    for (let i = 0; i < startPad; i++) result.push(null)
    // Days
    for (let d = 1; d <= lastDay.getDate(); d++) result.push(d)
    return result
  }, [viewState.year, viewState.month])

  const MONTHS = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']
  const WEEKDAYS = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']

  const prevMonth = () => setViewState((s) => {
    const m = s.month - 1
    return m < 0 ? { year: s.year - 1, month: 11 } : { ...s, month: m }
  })
  const nextMonth = () => setViewState((s) => {
    const m = s.month + 1
    return m > 11 ? { year: s.year + 1, month: 0 } : { ...s, month: m }
  })

  const isSelected = (d) => {
    if (!d || !value) return false
    const check = `${viewState.year}-${String(viewState.month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    return check === value
  }
  const isToday = (d) => {
    if (!d) return false
    return d === today.getDate() && viewState.month === today.getMonth() && viewState.year === today.getFullYear()
  }

  return (
    <div ref={ref} className="absolute top-full left-0 mt-1 z-50 bg-card border border-border rounded-lg shadow-xl p-3 w-64" onClick={(e) => e.stopPropagation()}>
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <button type="button" onClick={prevMonth} className="p-1 rounded hover:bg-card-alt text-text-muted hover:text-text-primary"><ChevronLeft size={14} /></button>
        <span className="text-xs font-medium text-text-primary">{MONTHS[viewState.month]} {viewState.year}</span>
        <button type="button" onClick={nextMonth} className="p-1 rounded hover:bg-card-alt text-text-muted hover:text-text-primary"><ChevronRight size={14} /></button>
      </div>
      {/* Weekday headers */}
      <div className="grid grid-cols-7 gap-0.5 mb-1">
        {WEEKDAYS.map((wd) => (
          <div key={wd} className="text-center text-[10px] text-text-muted font-medium py-0.5">{wd}</div>
        ))}
      </div>
      {/* Days */}
      <div className="grid grid-cols-7 gap-0.5">
        {days.map((d, i) => (
          <button
            key={i}
            type="button"
            disabled={!d}
            onClick={() => {
              if (!d) return
              const iso = `${viewState.year}-${String(viewState.month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
              onSelect(iso)
            }}
            className={`text-center text-xs py-1 rounded transition-colors ${
              !d ? '' :
              isSelected(d) ? 'bg-primary text-white font-medium' :
              isToday(d) ? 'bg-primary/15 text-primary font-medium' :
              'text-text-secondary hover:bg-card-alt hover:text-text-primary'
            }`}
          >
            {d || ''}
          </button>
        ))}
      </div>
      {/* Today button */}
      <button
        type="button"
        onClick={() => {
          const iso = today.toISOString().split('T')[0]
          onSelect(iso)
        }}
        className="w-full mt-2 text-xs text-center py-1 rounded text-primary hover:bg-primary/10 transition-colors"
      >
        Heute
      </button>
    </div>
  )
})
