import { createContext, useContext, useState, useCallback, useRef, useEffect } from 'react'
import { CheckCircle, XCircle, Info, AlertTriangle, X } from 'lucide-react'

const ToastContext = createContext()

export function useToast() {
  return useContext(ToastContext)
}

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])

  const addToast = useCallback((message, type = 'info') => {
    const id = Date.now()
    setToasts((prev) => [...prev, { id, message, type }])
  }, [])

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  return (
    <ToastContext.Provider value={addToast}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 space-y-2" role="status" aria-live="polite">
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={() => removeToast(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

const icons = {
  success: <CheckCircle size={16} className="text-success shrink-0" />,
  error: <XCircle size={16} className="text-danger shrink-0" />,
  warning: <AlertTriangle size={16} className="text-warning shrink-0" />,
  info: <Info size={16} className="text-primary shrink-0" />,
}

const styles = {
  success: 'border-success/30 bg-success/10',
  error: 'border-danger/30 bg-danger/10',
  warning: 'border-warning/30 bg-warning/10',
  info: 'border-primary/30 bg-primary/10',
}

function ToastItem({ toast, onDismiss }) {
  const timerRef = useRef(null)
  const remainingRef = useRef(3000)
  const startRef = useRef(Date.now())

  const startTimer = useCallback(() => {
    startRef.current = Date.now()
    timerRef.current = setTimeout(onDismiss, remainingRef.current)
  }, [onDismiss])

  const pauseTimer = useCallback(() => {
    clearTimeout(timerRef.current)
    remainingRef.current -= Date.now() - startRef.current
    if (remainingRef.current < 0) remainingRef.current = 0
  }, [])

  useEffect(() => {
    startTimer()
    return () => clearTimeout(timerRef.current)
  }, [startTimer])

  return (
    <div
      className={`flex items-center gap-2 rounded-lg border px-4 py-3 text-sm text-text-primary shadow-lg animate-slide-in ${styles[toast.type]}`}
      onMouseEnter={pauseTimer}
      onMouseLeave={startTimer}
    >
      {icons[toast.type]}
      <span>{toast.message}</span>
      <button onClick={onDismiss} className="ml-2 text-text-muted hover:text-text-primary">
        <X size={14} />
      </button>
    </div>
  )
}
