import { useApi } from '../hooks/useApi'
import { formatDate } from '../lib/format'

export default function StockNews({ ticker }) {
  const { data } = useApi(`/stock/${ticker}/news`)

  if (!data?.articles?.length) {
    if (data && Array.isArray(data.articles) && data.articles.length === 0) {
      return (
        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <div className="p-5">
            <h3 className="text-sm font-semibold text-text-primary mb-2">Nachrichten</h3>
            <p className="text-sm text-text-muted">News für {ticker} nicht verfügbar (FMP-Abo erforderlich).</p>
          </div>
        </div>
      )
    }
    return null
  }


  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="p-5">
        <h3 className="text-sm font-semibold text-text-primary mb-4">Nachrichten</h3>
        <div className="divide-y divide-border">
          {data.articles.map((article, i) => (
            <a
              key={i}
              href={article.url}
              target="_blank"
              rel="noopener noreferrer"
              className="block py-3 first:pt-0 last:pb-0 hover:bg-card-alt/30 transition-colors -mx-2 px-2 rounded"
            >
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm text-text-primary font-medium hover:text-primary leading-snug">
                  {article.title}
                </p>
                <span className="text-xs text-text-secondary whitespace-nowrap flex-shrink-0">
                  {formatDate(article.publishedDate)}
                </span>
              </div>
              {article.text && (
                <p className="text-xs text-text-secondary line-clamp-2 mt-1">{article.text}</p>
              )}
              {article.site && (
                <p className="text-xs text-text-secondary mt-1">{article.site}</p>
              )}
            </a>
          ))}
        </div>
      </div>
    </div>
  )
}
