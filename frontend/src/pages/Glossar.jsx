import { useState, useMemo } from 'react'
import { getAllGlossaryEntries, CATEGORY_LABELS } from '../data/glossary'
import { Search } from 'lucide-react'

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
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-text-primary">Glossar</h2>

      {/* Search + Filters */}
      <div className="space-y-3">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Begriff suchen..."
            className="w-full pl-9 pr-4 py-2 bg-card border border-border rounded-lg text-sm text-text-primary outline-none focus:border-primary placeholder:text-text-muted"
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setCategory(null)}
            className={`px-3 py-1 text-xs rounded-md transition-colors ${
              !category ? 'bg-primary text-white' : 'bg-card-alt text-text-secondary hover:text-text-primary'
            }`}
          >
            Alle
          </button>
          {CATEGORIES.map(([key, label]) => (
            <button
              key={key}
              onClick={() => setCategory(category === key ? null : key)}
              className={`px-3 py-1 text-xs rounded-md transition-colors ${
                category === key ? 'bg-primary text-white' : 'bg-card-alt text-text-secondary hover:text-text-primary'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Entries */}
      <div className="space-y-3">
        {filtered.length === 0 && (
          <p className="text-sm text-text-muted py-8 text-center">Keine Einträge gefunden.</p>
        )}
        {filtered.map(entry => (
          <div
            key={entry.key}
            id={`glossar-${entry.key.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')}`}
            className="rounded-lg border border-border bg-card p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-text-primary font-mono">{entry.key}</h3>
                <p className="text-sm text-text-secondary mt-1">{entry.short}</p>
                {entry.long && (
                  <p className="text-xs text-text-muted mt-2 leading-relaxed">{entry.long}</p>
                )}
              </div>
              <span className="text-[10px] text-text-muted bg-card-alt px-2 py-0.5 rounded shrink-0">
                {CATEGORY_LABELS[entry.category] || entry.category}
              </span>
            </div>
          </div>
        ))}
      </div>

      <p className="text-xs text-text-muted text-center pb-4">{filtered.length} von {allEntries.length} Begriffen</p>
    </div>
  )
}
