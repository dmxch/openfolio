import { useState } from 'react'
import { Newspaper, ExternalLink } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { formatDate } from '../lib/format'
import TickerLogo from '../components/TickerLogo'

const SCOPES = [
  { value: 'all', label: 'Alle' },
  { value: 'portfolio', label: 'Portfolio' },
  { value: 'watchlist', label: 'Watchlist' },
]

export default function News() {
  const [scope, setScope] = useState('all')

  const { data, loading } = useApi(`/news?scope=${scope}&limit=100`)
  const articles = data?.articles || []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Newspaper size={22} className="text-primary" />
          <h2 className="text-xl font-bold text-text-primary">Nachrichten</h2>
          <span className="text-sm text-text-muted">Aktuelle News zu deinen Positionen</span>
        </div>
      </div>

      {/* Scope tabs */}
      <div className="flex gap-1 bg-card-alt/50 rounded-lg p-1 w-fit">
        {SCOPES.map(s => (
          <button
            key={s.value}
            onClick={() => setScope(s.value)}
            className={`px-4 py-1.5 rounded-md text-sm transition-colors ${
              scope === s.value
                ? 'bg-card text-text-primary font-medium shadow-sm'
                : 'text-text-muted hover:text-text-secondary'
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* Articles */}
      {loading && (
        <div className="bg-card border border-border rounded-xl p-8 text-center">
          <p className="text-text-muted text-sm">Lade Nachrichten...</p>
        </div>
      )}

      {!loading && articles.length === 0 && (
        <div className="bg-card border border-border rounded-xl p-12 text-center">
          <Newspaper size={40} className="text-text-muted mx-auto mb-4" />
          <p className="text-text-secondary">
            Noch keine Nachrichten vorhanden. Der News-Feed wird automatisch zweimal täglich aktualisiert.
          </p>
        </div>
      )}

      {!loading && articles.length > 0 && (
        <div className="bg-card border border-border rounded-xl overflow-hidden divide-y divide-border">
          {articles.map((article, i) => (
            <a
              key={i}
              href={article.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-start gap-4 px-5 py-4 hover:bg-card-alt/30 transition-colors"
            >
              <TickerLogo ticker={article.ticker} size={24} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-mono font-semibold text-primary">{article.ticker}</span>
                  {article.source && (
                    <span className="text-xs text-text-muted">{article.source}</span>
                  )}
                  {article.published_at && (
                    <span className="text-xs text-text-muted ml-auto shrink-0">
                      {formatDate(article.published_at)}
                    </span>
                  )}
                </div>
                <p className="text-sm text-text-primary font-medium leading-snug line-clamp-2">
                  {article.title}
                </p>
                {article.snippet && (
                  <p className="text-xs text-text-secondary line-clamp-2 mt-1">{article.snippet}</p>
                )}
              </div>
              <ExternalLink size={14} className="text-text-muted shrink-0 mt-1" />
            </a>
          ))}
        </div>
      )}
    </div>
  )
}
