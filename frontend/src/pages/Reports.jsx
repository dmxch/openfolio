import { useState, useMemo, useEffect } from 'react'
import { FileText, Download, Trash2, X, Search, Plus } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useApi, authFetch, apiPatch, apiDelete } from '../hooks/useApi'
import useDebouncedValue from '../hooks/useDebouncedValue'
import { useToast } from '../components/Toast'
import { formatDate } from '../lib/format'

// Kategorie-Labels (Finance-Workspace-Slugs → DE-Anzeige).
const CATEGORY_LABELS = {
  daily_brief: 'Daily Brief',
  weekly_check: 'Weekly Check',
  trade: 'Trade-Plan',
  earnings: 'Earnings',
  institutional_flow: 'Institutional Flow',
  macro: 'Makro',
  review: 'Review',
  strategy: 'Strategie',
  decision: 'Decision',
  quarterly_review: 'Quartals-Review',
  concept: 'Konzept',
  discovery: 'Discovery',
  sektor_only: 'Sektor',
  other: 'Sonstiges',
}

function catLabel(c) {
  return CATEGORY_LABELS[c] || c
}

// Markdown-Renderer-Komponenten — Dark-Theme-Styling ohne Typography-Plugin.
const MD_COMPONENTS = {
  h1: (p) => <h1 className="text-2xl font-bold text-text-primary mt-6 mb-3 first:mt-0" {...p} />,
  h2: (p) => <h2 className="text-xl font-semibold text-text-primary mt-5 mb-2 border-b border-border pb-1" {...p} />,
  h3: (p) => <h3 className="text-base font-semibold text-text-primary mt-4 mb-2" {...p} />,
  p: (p) => <p className="text-sm text-text-secondary leading-relaxed mb-3" {...p} />,
  ul: (p) => <ul className="list-disc pl-5 text-sm text-text-secondary mb-3 space-y-1" {...p} />,
  ol: (p) => <ol className="list-decimal pl-5 text-sm text-text-secondary mb-3 space-y-1" {...p} />,
  li: (p) => <li className="leading-relaxed" {...p} />,
  a: (p) => <a className="text-primary hover:underline" target="_blank" rel="noopener noreferrer" {...p} />,
  strong: (p) => <strong className="font-semibold text-text-primary" {...p} />,
  blockquote: (p) => <blockquote className="border-l-[3px] border-primary/50 pl-3 italic text-text-muted my-3" {...p} />,
  code: ({ inline, ...p }) =>
    inline
      ? <code className="bg-card-alt px-1.5 py-0.5 rounded text-xs font-mono text-primary" {...p} />
      : <code className="block bg-card-alt p-3 rounded text-xs font-mono text-text-secondary overflow-x-auto my-3" {...p} />,
  hr: () => <hr className="border-border my-4" />,
  table: (p) => <div className="overflow-x-auto my-3"><table className="w-full text-sm border border-border" {...p} /></div>,
  th: (p) => <th className="text-left p-2 border border-border bg-card-alt text-text-primary font-medium" {...p} />,
  td: (p) => <td className="p-2 border border-border text-text-secondary" {...p} />,
}

function CategoryBadge({ category }) {
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-primary/15 text-primary">
      {catLabel(category)}
    </span>
  )
}

function ReportViewer({ id, onDeleted, onTagsChanged }) {
  const { data, loading, error } = useApi(`/reports/${id}`)
  const [tags, setTags] = useState([])
  const [tagInput, setTagInput] = useState('')
  const toast = useToast()

  useEffect(() => {
    setTags(data?.tags || [])
  }, [data])

  if (loading) return <div className="p-8 text-text-muted">Lade Report…</div>
  if (error) return <div className="p-8 text-danger">Fehler: {error}</div>
  if (!data) return null

  async function saveTags(next) {
    try {
      const res = await apiPatch(`/reports/${id}`, { tags: next })
      setTags(res.tags)
      onTagsChanged?.()
    } catch (e) {
      toast(`Tags speichern fehlgeschlagen: ${e.message}`, 'error')
    }
  }

  function addTag() {
    const t = tagInput.trim()
    if (!t || tags.includes(t)) { setTagInput(''); return }
    const next = [...tags, t]
    setTagInput('')
    saveTags(next)
  }

  function removeTag(t) {
    saveTags(tags.filter((x) => x !== t))
  }

  async function handleExport() {
    try {
      const res = await authFetch(`/api/reports/${id}/export`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const cd = res.headers.get('content-disposition') || ''
      const m = cd.match(/filename="([^"]+)"/)
      a.download = m ? m[1] : 'report.md'
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      toast(`Export fehlgeschlagen: ${e.message}`, 'error')
    }
  }

  async function handleDelete() {
    if (!window.confirm('Diesen Report wirklich löschen?')) return
    try {
      await apiDelete(`/reports/${id}`)
      toast('Report gelöscht', 'success')
      onDeleted?.()
    } catch (e) {
      toast(`Löschen fehlgeschlagen: ${e.message}`, 'error')
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-start justify-between gap-4 p-4 border-b border-border">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <CategoryBadge category={data.category} />
            {data.report_date && <span className="text-xs text-text-muted">{formatDate(data.report_date)}</span>}
            {data.source && <span className="text-xs text-text-muted">· {data.source}</span>}
          </div>
          <h2 className="text-lg font-semibold text-text-primary truncate">{data.title}</h2>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button onClick={handleExport} title="Als Markdown exportieren"
            className="p-2 rounded hover:bg-card-hover text-text-secondary"><Download size={16} /></button>
          <button onClick={handleDelete} title="Löschen"
            className="p-2 rounded hover:bg-danger/10 text-text-muted hover:text-danger"><Trash2 size={16} /></button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5 px-4 py-2 border-b border-border">
        {tags.map((t) => (
          <span key={t} className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-card-alt text-text-secondary">
            {t}
            <button onClick={() => removeTag(t)} className="hover:text-danger"><X size={11} /></button>
          </span>
        ))}
        <span className="inline-flex items-center gap-1">
          <input
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') addTag() }}
            placeholder="Tag…"
            className="w-20 bg-transparent border-b border-border text-xs px-1 py-0.5 focus:outline-none focus:border-primary"
          />
          <button onClick={addTag} className="text-text-muted hover:text-primary"><Plus size={12} /></button>
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>
          {data.body || ''}
        </ReactMarkdown>
      </div>
    </div>
  )
}

export default function Reports() {
  const [selected, setSelected] = useState(null)
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [tag, setTag] = useState('')
  const debouncedSearch = useDebouncedValue(search, 300)

  const query = useMemo(() => {
    const p = new URLSearchParams()
    p.set('per_page', '100')
    if (debouncedSearch) p.set('q', debouncedSearch)
    if (category) p.set('category', category)
    if (tag) p.set('tag', tag)
    return p.toString()
  }, [debouncedSearch, category, tag])

  const { data, loading, error, refetch } = useApi(`/reports?${query}`)

  const results = data?.results ?? []
  const categories = data?.categories ?? []
  const allTags = data?.all_tags ?? []

  // Auto-select first result when selection is gone.
  useEffect(() => {
    if (results.length && !results.find((r) => r.id === selected)) {
      setSelected(results[0].id)
    }
    if (!results.length) setSelected(null)
  }, [results, selected])

  return (
    <div className="p-6">
      <header className="mb-4">
        <div className="flex items-center gap-3 mb-1">
          <FileText size={24} className="text-primary" />
          <h1 className="text-2xl font-semibold">Report-Vault</h1>
        </div>
        <p className="text-sm text-text-muted">
          Alle generierten Claude-Finance-Briefe — durchsuchbar, tagbar, exportierbar.
        </p>
      </header>

      <div className="flex gap-6 h-[calc(100vh-180px)]">
        {/* Liste + Filter */}
        <div className="w-96 shrink-0 flex flex-col border border-border rounded-lg overflow-hidden">
          <div className="p-3 border-b border-border space-y-2">
            <div className="relative">
              <Search size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Volltext-Suche…"
                className="w-full pl-7 pr-2 py-1.5 bg-card-alt rounded text-sm focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
            <div className="flex gap-2">
              <select value={category} onChange={(e) => setCategory(e.target.value)}
                className="flex-1 bg-card-alt rounded text-xs px-2 py-1.5 focus:outline-none">
                <option value="">Alle Kategorien</option>
                {categories.map((c) => <option key={c} value={c}>{catLabel(c)}</option>)}
              </select>
              <select value={tag} onChange={(e) => setTag(e.target.value)}
                className="flex-1 bg-card-alt rounded text-xs px-2 py-1.5 focus:outline-none">
                <option value="">Alle Tags</option>
                {allTags.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto">
            {loading && results.length === 0 && <div className="p-4 text-sm text-text-muted">Lade…</div>}
            {error && <div className="p-4 text-sm text-danger">Fehler: {error}</div>}
            {!loading && results.length === 0 && !error && (
              <div className="p-4 text-sm text-text-muted">
                Noch keine Reports. Der Finance-Workspace pusht sie via API.
              </div>
            )}
            {results.map((r) => (
              <button
                key={r.id}
                onClick={() => setSelected(r.id)}
                className={`w-full text-left px-3 py-2.5 border-b border-border/50 transition-colors ${
                  selected === r.id ? 'bg-card-hover border-l-[3px] border-l-primary' : 'hover:bg-card-alt border-l-[3px] border-l-transparent'
                }`}
              >
                <div className="flex items-center justify-between gap-2 mb-0.5">
                  <CategoryBadge category={r.category} />
                  {r.report_date && <span className="text-[11px] text-text-muted">{formatDate(r.report_date)}</span>}
                </div>
                <div className="text-sm text-text-primary truncate">{r.title}</div>
                {r.tags?.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {r.tags.map((t) => <span key={t} className="text-[10px] text-text-muted bg-card-alt px-1.5 rounded">{t}</span>)}
                  </div>
                )}
              </button>
            ))}
          </div>
          <div className="px-3 py-2 border-t border-border text-xs text-text-muted">
            {data?.total ?? 0} Report{(data?.total ?? 0) === 1 ? '' : 's'}
          </div>
        </div>

        {/* Viewer */}
        <div className="flex-1 min-w-0 border border-border rounded-lg overflow-hidden bg-card">
          {selected ? (
            <ReportViewer
              key={selected}
              id={selected}
              onDeleted={() => { setSelected(null); refetch() }}
              onTagsChanged={refetch}
            />
          ) : (
            <div className="flex items-center justify-center h-full text-text-muted text-sm">
              Wähle einen Report aus der Liste.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
