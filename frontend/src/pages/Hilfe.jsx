import { useState, useEffect, useMemo } from 'react'
import { useLocation, Link } from 'react-router-dom'
import { Search, ChevronDown, ArrowRight } from 'lucide-react'
import { HELP_SECTIONS } from '../data/helpContent'
import PageHeader from '../components/ui/PageHeader'

function renderContent(text) {
  if (!text) return null
  const lines = text.split('\n')
  const elements = []

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim()
    if (!line) continue

    if (line.startsWith('## ')) {
      elements.push(<h3 key={i} className="text-sm font-semibold text-text-primary mt-5 mb-2">{line.slice(3)}</h3>)
    } else if (line.startsWith('> ')) {
      elements.push(
        <div key={i} className="rounded-lg border border-primary/20 bg-primary/5 px-4 py-3 text-sm text-text-secondary my-3">
          {renderInline(line.slice(2))}
        </div>
      )
    } else {
      elements.push(<p key={i} className="text-sm text-text-secondary leading-relaxed mb-3">{renderInline(line)}</p>)
    }
  }

  return elements
}

function renderInline(text) {
  // Bold
  const parts = text.split(/(\*\*[^*]+\*\*|\[[^\]]+\]\(#[^)]+\))/)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i} className="text-text-primary font-medium">{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('[')) {
      const match = part.match(/\[([^\]]+)\]\(#([^)]+)\)/)
      if (match) {
        return <a key={i} href={`/hilfe#${match[2]}`} className="text-link hover:underline">{match[1]}</a>
      }
    }
    return part
  })
}

function FaqCard({ article, open, onToggle }) {
  return (
    <div id={`faq-${article.id}`} className="bg-card border border-border rounded-card overflow-hidden scroll-mt-24">
      <button
        onClick={onToggle}
        aria-expanded={open}
        className="w-full flex items-center justify-between gap-4 px-[18px] py-[14px] text-left hover:bg-hover transition-colors"
      >
        <span className="text-sm font-medium text-text-primary">{article.title}</span>
        <ChevronDown
          size={16}
          className={`shrink-0 text-text-muted transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && (
        <div className="px-[18px] py-4 border-t border-border-2">
          {article.summary && (
            <p className="text-sm text-primary font-medium mb-3">{article.summary}</p>
          )}
          <div className="max-w-none">
            {renderContent(article.content)}
          </div>
          {article.id === 'glossar-link' && (
            <Link
              to="/glossar"
              className="inline-flex items-center gap-1.5 mt-2 text-[13px] text-link hover:text-primary transition-colors"
            >
              Zum vollständigen Glossar
              <ArrowRight size={14} />
            </Link>
          )}
        </div>
      )}
    </div>
  )
}

export default function Hilfe() {
  const location = useLocation()
  const [query, setQuery] = useState('')
  const [openIds, setOpenIds] = useState(() => new Set())

  // Open + scroll to the article referenced by the URL hash (e.g. #glossar-link)
  useEffect(() => {
    const hash = location.hash?.slice(1)
    if (!hash) return
    setOpenIds(prev => {
      const next = new Set(prev)
      next.add(hash)
      return next
    })
    const t = setTimeout(() => {
      document.getElementById(`faq-${hash}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 50)
    return () => clearTimeout(t)
  }, [location.hash])

  const toggle = (id) => setOpenIds(prev => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  const filtered = useMemo(() => {
    if (!query.trim()) return HELP_SECTIONS
    const q = query.toLowerCase()
    return HELP_SECTIONS.map(s => ({
      ...s,
      articles: s.articles.filter(a =>
        a.title.toLowerCase().includes(q) ||
        a.summary?.toLowerCase().includes(q) ||
        a.content?.toLowerCase().includes(q)
      ),
    })).filter(s => s.articles.length > 0)
  }, [query])

  const isEmpty = filtered.length === 0

  return (
    <div className="pb-10">
      <PageHeader
        title="Hilfe"
        subtitle="Anleitungen & Konzepte"
        showBell={false}
        showSearch={false}
        actions={
          <Link
            to="/glossar"
            className="inline-flex items-center gap-1.5 text-[13px] text-link hover:text-primary transition-colors"
          >
            Glossar
            <ArrowRight size={14} />
          </Link>
        }
      />

      <div className="max-w-[760px] mx-auto flex flex-col gap-[18px]">
        {/* Hero: heading + centered search */}
        <div className="text-center pt-2 pb-1">
          <h2 className="text-[26px] font-semibold tracking-[-0.01em] text-text-primary">
            Wie können wir helfen?
          </h2>
          <p className="text-sm text-text-muted mt-2">
            Durchsuche Anleitungen, Konzepte und Begriffe.
          </p>
          <div className="relative max-w-[480px] mx-auto mt-5">
            <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-text-muted" />
            <input
              aria-label="Hilfe durchsuchen"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Hilfe durchsuchen…"
              className="w-full pl-11 pr-4 py-[11px] bg-surface border border-border rounded-card text-sm text-text-primary outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 placeholder:text-text-muted transition-colors"
            />
          </div>
        </div>

        {/* FAQ */}
        {isEmpty ? (
          <div className="rounded-card border border-border bg-card text-center py-16">
            <p className="text-sm text-text-muted">
              Keine Hilfe-Artikel gefunden{query ? ` für „${query}“` : ''}.
            </p>
          </div>
        ) : (
          filtered.map(section => (
            <div key={section.id}>
              <div className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label mb-2.5 px-1">
                {section.title}
              </div>
              <div className="flex flex-col gap-2.5">
                {section.articles.map(article => (
                  <FaqCard
                    key={article.id}
                    article={article}
                    open={openIds.has(article.id)}
                    onToggle={() => toggle(article.id)}
                  />
                ))}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
