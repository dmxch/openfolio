import { Check, X } from 'lucide-react'

const RULES = [
  { test: (p) => p.length >= 12, label: 'Mindestens 12 Zeichen' },
  { test: (p) => /[A-Z]/.test(p), label: 'Grossbuchstabe' },
  { test: (p) => /[a-z]/.test(p), label: 'Kleinbuchstabe' },
  { test: (p) => /\d/.test(p), label: 'Zahl' },
  { test: (p) => /[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]/.test(p), label: 'Sonderzeichen' },
]

export default function PasswordStrength({ password }) {
  if (!password) return null

  const results = RULES.map(r => ({ ...r, passed: r.test(password) }))
  const passedCount = results.filter(r => r.passed).length
  const strength = passedCount <= 2 ? 'weak' : passedCount <= 4 ? 'medium' : 'strong'
  const barColor = strength === 'weak' ? 'bg-danger' : strength === 'medium' ? 'bg-warning' : 'bg-success'
  const barWidth = `${(passedCount / RULES.length) * 100}%`

  return (
    <div className="mt-2 space-y-1.5">
      <div className="h-1 bg-card-alt rounded-full overflow-hidden">
        <div className={`h-full ${barColor} transition-all duration-300 rounded-full`} style={{ width: barWidth }} />
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
        {results.map(r => (
          <div key={r.label} className="flex items-center gap-1.5 text-[11px]">
            {r.passed
              ? <Check size={10} className="text-success shrink-0" />
              : <X size={10} className="text-text-muted shrink-0" />
            }
            <span className={r.passed ? 'text-text-secondary' : 'text-text-muted'}>{r.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
