import { Link } from 'react-router-dom'

export default function DisclaimerBanner({ className }) {
  return (
    <div className={`text-xs text-text-muted mt-4 ${className || ''}`}>
      <span className="opacity-60">
        Technische Indikatoren, keine Anlageberatung. Keine Gewähr auf Richtigkeit.{' '}
        <Link to="/rechtliches#disclaimer" className="underline hover:text-text-secondary">
          Rechtlicher Hinweis
        </Link>
      </span>
    </div>
  )
}
