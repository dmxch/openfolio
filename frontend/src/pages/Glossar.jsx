import { useState, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { getAllGlossaryEntries, CATEGORY_LABELS } from '../data/glossary'
import { Search, ArrowLeft } from 'lucide-react'
import PageHeader from '../components/ui/PageHeader'

const CATEGORIES = Object.entries(CATEGORY_LABELS)

export default function Glossar() {
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState(null)

  const allEntries = useMemo(() => getAllGlossaryEntries(), [])

  const filtered = useMemo(() => {
    let entries = allEntries
    if (category) entries = entries.filter(e => e.category === category)
    if (query.trim()) {
      const q = query.toLowerCase()
      entries = entries.filter(e =>
        e.key.toLowerCase().includes(q) ||
        e.short.toLowerCase().includes(q) ||
        (e.long && e.long.toLowerCase().includes(q))
      )
    }
    return entries
  }, [allEntries, query, category])

  return (
    <div className="pb-10">
      <PageHeader
        title="Glossar"
        subtitle={`${allEntries.length} Begriffe`}
        showBell={false}
        showSearch={false}
        actions={
          <>
            <Link
              to="/hilfe"
              className="inline-flex items-center gap-1.5 text-[13px] text-link hover:text-primary transition-colors"
            >
              <ArrowLeft size={14} />
              Hilfe
            </Link>
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
              <input
                aria-label="Begriff suchen"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Begriff suchen…"
                className="w-[240px] pl-9 pr-3 py-[7px] bg-surface border border-border rounded-lg text-[12.5px] text-text-primary outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 placeholder:text-text-muted transition-colors"
              />
            </div>
          </>
        }
      />

      <div className="max-w-[1000px] mx-auto flex flex-col gap-[18px]">
        {/* Category filter */}
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setCategory(null)}
            className={`px-3 py-[5px] text-xs rounded-lg border transition-colors ${
              !category
                ? 'bg-active-tint border-border-active text-text-primary'
                : 'bg-surface border-border text-text-secondary hover:border-border-hover hover:text-text-primary'
            }`}
          >
            Alle
          </button>
          {CATEGORIES.map(([key, label]) => (
            <button
              key={key}
              onClick={() => setCategory(category === key ? null : key)}
              className={`px-3 py-[5px] text-xs rounded-lg border transition-colors ${
                category === key
                  ? 'bg-active-tint border-border-active text-text-primary'
                  : 'bg-surface border-border text-text-secondary hover:border-border-hover hover:text-text-primary'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Entries */}
        {filtered.length === 0 ? (
          <div className="rounded-card border border-border bg-card text-center py-16">
            <p className="text-sm text-text-muted">Keine Einträge gefunden.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-[14px]">
            {filtered.map(entry => (
              <div
                key={entry.key}
                id={`glossar-${entry.key.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')}`}
                className="bg-card border border-border rounded-card p-[18px] scroll-mt-24"
              >
                <div className="flex items-start justify-between gap-3 mb-2">
                  <h3 className="text-sm font-semibold text-text-primary font-mono">{entry.key}</h3>
                  <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.05em] text-link bg-link/10 px-2 py-0.5 rounded">
                    {CATEGORY_LABELS[entry.category] || entry.category}
                  </span>
                </div>
                <p className="text-sm text-text-secondary leading-relaxed">{entry.short}</p>
                {entry.long && (
                  <p className="text-xs text-text-muted mt-2 leading-relaxed">{entry.long}</p>
                )}
              </div>
            ))}
          </div>
        )}

        <p className="text-xs text-text-muted text-center pb-2">
          {filtered.length} von {allEntries.length} Begriffen
        </p>
      </div>
    </div>
  )
}
