import { useState, useMemo, useEffect } from 'react'
import { FileText, Download, Trash2, X, Search, Plus } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useApi, authFetch, apiPatch, apiDelete } from '../hooks/useApi'
import useDebouncedValue from '../hooks/useDebouncedValue'
import { useToast } from '../components/Toast'
import { formatDate } from '../lib/format'
import PageHeader from '../components/ui/PageHeader'
import FilterChips from '../components/ui/FilterChips'
import Button from '../components/ui/Button'
import Skeleton from '../components/Skeleton'
import { Badge, tint } from '../components/ui/Badge'

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

// Akzentfarben pro Kategorie (nur Styling — keine Datenbedeutung).
const CATEGORY_COLORS = {
  daily_brief: '#5b8def',
  weekly_check: '#29c3b1',
  trade: '#45c08a',
  earnings: '#e0a64b',
  institutional_flow: '#8a7de0',
  macro: '#6b8aa0',
  review: '#b06ee8',
  strategy: '#5b8def',
  decision: '#e8625a',
  quarterly_review: '#b06ee8',
  concept: '#7a8698',
  discovery: '#29c3b1',
  sektor_only: '#e0a64b',
  other: '#7a8698',
}

function catLabel(c) {
  return CATEGORY_LABELS[c] || c
}

function catColor(c) {
  return CATEGORY_COLORS[c] || '#7a8698'
}

const INPUT =
  'bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder:text-text-faint focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors'

// Markdown-Renderer-Komponenten — Dark-Theme-Styling auf Design-Tokens (ohne Typography-Plugin).
const MD_COMPONENTS = {
  h1: (p) => <h1 className="text-[22px] font-bold text-text-primary mt-7 mb-3 first:mt-0" {...p} />,
  h2: (p) => <h2 className="text-lg font-semibold text-text-primary mt-6 mb-2 pb-1.5 border-b border-border-2" {...p} />,
  h3: (p) => <h3 className="text-[15px] font-semibold text-text-primary mt-5 mb-2" {...p} />,
  p: (p) => <p className="text-[13.5px] text-text-secondary leading-relaxed mb-3" {...p} />,
  ul: (p) => <ul className="list-disc pl-5 text-[13.5px] text-text-secondary mb-3 space-y-1 marker:text-text-faint" {...p} />,
  ol: (p) => <ol className="list-decimal pl-5 text-[13.5px] text-text-secondary mb-3 space-y-1 marker:text-text-faint" {...p} />,
  li: (p) => <li className="leading-relaxed" {...p} />,
  a: (p) => <a className="text-link hover:underline" target="_blank" rel="noopener noreferrer" {...p} />,
  strong: (p) => <strong className="font-semibold text-text-primary" {...p} />,
  blockquote: (p) => <blockquote className="border-l-[3px] border-border-active pl-4 italic text-text-muted my-4" {...p} />,
  code: ({ inline, ...p }) =>
    inline
      ? <code className="bg-table-head border border-border-2 px-1.5 py-0.5 rounded text-[12px] font-mono text-text-primary" {...p} />
      : <code className="block bg-table-head border border-border-2 p-3 rounded-lg text-[12px] font-mono text-text-secondary overflow-x-auto my-3" {...p} />,
  hr: () => <hr className="border-border-2 my-5" />,
  table: (p) => <div className="overflow-x-auto my-4"><table className="w-full text-[13px] border border-border-2 border-collapse" {...p} /></div>,
  th: (p) => <th className="text-left p-2 border border-border-2 bg-table-head text-text-primary font-medium" {...p} />,
  td: (p) => <td className="p-2 border border-border-2 text-text-secondary" {...p} />,
}

function CategoryBadge({ category }) {
  const color = catColor(category)
  return <Badge color={color} bg={tint(color)}>{catLabel(category)}</Badge>
}

function ReportViewer({ id, onDeleted, onTagsChanged }) {
  const { data, loading, error } = useApi(`/reports/${id}`)
  const [tags, setTags] = useState([])
  const [tagInput, setTagInput] = useState('')
  const toast = useToast()

  useEffect(() => {
    setTags(data?.tags || [])
  }, [data])

  if (loading) return <div className="p-8 text-sm text-text-muted">Lade Report…</div>
  if (error) {
    return (
      <div className="p-7">
        <div className="rounded-card border border-danger/30 bg-danger/10 p-4 text-danger text-sm">Fehler: {error}</div>
      </div>
    )
  }
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
    <div className="px-7 py-6 max-w-[760px]">
      {/* Kopf: Kategorie/Datum/Quelle + Aktionen */}
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          <CategoryBadge category={data.category} />
          {data.report_date && (
            <span className="font-mono text-[11px] text-text-faint">{formatDate(data.report_date)}</span>
          )}
          {data.source && (
            <span className="font-mono text-[11px] text-text-faint">· {data.source}</span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button variant="secondary" icon={Download} onClick={handleExport}>Export MD</Button>
          <button
            onClick={handleDelete}
            title="Löschen"
            aria-label="Report löschen"
            className="inline-flex items-center justify-center w-9 h-9 rounded-lg bg-surface border border-border text-text-muted hover:text-danger hover:border-danger/40 transition-colors"
          >
            <Trash2 size={15} />
          </button>
        </div>
      </div>

      {/* Titel */}
      <h1 className="text-[24px] font-semibold tracking-[-0.01em] text-text-primary leading-tight mb-4">
        {data.title}
      </h1>

      {/* Inline-Tags + Tag hinzufügen */}
      <div className="flex flex-wrap items-center gap-1.5 mb-6 pb-6 border-b border-border-2">
        {tags.map((t) => (
          <span
            key={t}
            className="inline-flex items-center gap-1 font-mono text-[11px] text-text-secondary bg-surface border border-border-chip rounded-md px-2 py-1"
          >
            {t}
            <button onClick={() => removeTag(t)} className="text-text-faint hover:text-danger transition-colors" aria-label={`Tag ${t} entfernen`}>
              <X size={11} />
            </button>
          </span>
        ))}
        <span className="inline-flex items-center gap-1 bg-surface border border-border-chip rounded-md pl-2 pr-1 py-0.5">
          <input
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') addTag() }}
            placeholder="Tag…"
            aria-label="Tag hinzufügen"
            className="w-20 bg-transparent text-[11px] text-text-primary placeholder:text-text-faint focus:outline-none"
          />
          <button onClick={addTag} className="text-text-muted hover:text-primary transition-colors" aria-label="Tag speichern">
            <Plus size={13} />
          </button>
        </span>
      </div>

      {/* Markdown-Body */}
      <div>
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
  const total = data?.total ?? 0
  const hasFilters = !!(debouncedSearch || category || tag)

  // Auto-select first result when selection is gone.
  useEffect(() => {
    if (results.length && !results.find((r) => r.id === selected)) {
      setSelected(results[0].id)
    }
    if (!results.length) setSelected(null)
  }, [results, selected])

  const catOptions = [
    { key: '', label: 'Alle' },
    ...categories.map((c) => ({ key: c, label: catLabel(c) })),
  ]

  return (
    <div className="pb-10">
      <PageHeader
        title="Report-Vault"
        subtitle={`${total} ${total === 1 ? 'Eintrag' : 'Einträge'}`}
        showBell={false}
      />

      <div className="grid grid-cols-[400px_1fr] rounded-card border border-border bg-card overflow-hidden h-[calc(100vh-130px)]">
        {/* LINKS: Liste + Filter */}
        <div className="flex flex-col min-h-0 border-r border-border-soft">
          <div className="p-[18px] border-b border-border-2 flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Volltext-Suche…"
                  aria-label="Reports durchsuchen"
                  className={`${INPUT} pl-8 w-full text-xs h-[34px]`}
                />
                {search && (
                  <button
                    onClick={() => setSearch('')}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary"
                    aria-label="Suche löschen"
                  >
                    <X size={12} />
                  </button>
                )}
              </div>
              {allTags.length > 0 && (
                <select
                  value={tag}
                  onChange={(e) => setTag(e.target.value)}
                  aria-label="Nach Tag filtern"
                  className="bg-surface border border-border rounded-lg text-xs text-text-secondary px-2 h-[34px] max-w-[120px] focus:outline-none focus:border-primary transition-colors"
                >
                  <option value="">Alle Tags</option>
                  {allTags.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              )}
            </div>
            {catOptions.length > 1 && (
              <FilterChips options={catOptions} value={category} onChange={(k) => setCategory(k)} />
            )}
          </div>

          <div className="flex-1 overflow-y-auto min-h-0">
            {loading && results.length === 0 && (
              <div className="p-3 flex flex-col gap-2">
                {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-[68px] rounded-lg" />)}
              </div>
            )}
            {error && (
              <div className="m-3 rounded-card border border-danger/30 bg-danger/10 p-3 text-sm text-danger">Fehler: {error}</div>
            )}
            {!loading && results.length === 0 && !error && (
              <div className="flex flex-col items-center justify-center h-full text-center px-6 py-10">
                <div className="w-12 h-12 rounded-full bg-surface border border-border flex items-center justify-center mb-3">
                  <FileText className="w-5 h-5 text-text-faint" />
                </div>
                {hasFilters ? (
                  <p className="text-sm text-text-secondary">Keine Treffer für diese Filter.</p>
                ) : (
                  <>
                    <p className="text-sm text-text-secondary">Noch keine Reports</p>
                    <p className="text-xs text-text-faint mt-1">Der Finance-Workspace pusht sie via API.</p>
                  </>
                )}
              </div>
            )}
            {results.map((r) => {
              const active = selected === r.id
              return (
                <button
                  key={r.id}
                  onClick={() => setSelected(r.id)}
                  className={`w-full text-left px-4 py-3 border-b border-border-row border-l-2 transition-colors ${
                    active
                      ? 'bg-active-tint border-l-border-active'
                      : 'border-l-transparent hover:bg-hover'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2 mb-1.5">
                    <CategoryBadge category={r.category} />
                    {r.report_date && (
                      <span className="font-mono text-[10.5px] text-text-faint shrink-0">{formatDate(r.report_date)}</span>
                    )}
                  </div>
                  <div className="text-[13px] font-medium text-text-primary truncate">{r.title}</div>
                  {r.tags?.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {r.tags.map((t) => (
                        <span key={t} className="font-mono text-[10px] text-text-muted bg-surface border border-border-chip rounded px-1.5 py-0.5">{t}</span>
                      ))}
                    </div>
                  )}
                </button>
              )
            })}
          </div>
        </div>

        {/* RECHTS: Viewer */}
        <div className="overflow-y-auto min-h-0">
          {selected ? (
            <ReportViewer
              key={selected}
              id={selected}
              onDeleted={() => { setSelected(null); refetch() }}
              onTagsChanged={refetch}
            />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center px-6">
              <div className="w-14 h-14 rounded-full bg-surface border border-border flex items-center justify-center mb-4">
                <FileText className="w-6 h-6 text-text-faint" />
              </div>
              <p className="text-sm text-text-secondary">Wähle einen Report aus der Liste.</p>
              <p className="text-xs text-text-faint mt-1">Briefe aus dem Finance-Workspace erscheinen hier.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
