import { useState, useEffect, useMemo, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { Search, ChevronDown, ChevronRight, Menu, X } from 'lucide-react'
import { HELP_SECTIONS } from '../data/helpContent'
import G from '../components/GlossarTooltip'
import Glossar from './Glossar'

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
        return <a key={i} href={`/hilfe#${match[2]}`} className="text-primary hover:underline">{match[1]}</a>
      }
    }
    return part
  })
}

function SidebarNav({ sections, activeArticle, onSelect, query, onQueryChange }) {
  const [collapsed, setCollapsed] = useState(() => {
    const init = {}
    sections.forEach(s => { init[s.id] = true })
    // Open the section containing the active article
    if (activeArticle) {
      const match = sections.find(s => s.articles.some(a => a.id === activeArticle))
      if (match) init[match.id] = false
    }
    return init
  })

  const toggle = (id) => setCollapsed(prev => ({ ...prev, [id]: !prev[id] }))

  const filtered = useMemo(() => {
    if (!query.trim()) return sections
    const q = query.toLowerCase()
    return sections.map(s => ({
      ...s,
      articles: s.articles.filter(a =>
        a.title.toLowerCase().includes(q) ||
        a.summary?.toLowerCase().includes(q) ||
        a.content?.toLowerCase().includes(q)
      )
    })).filter(s => s.articles.length > 0)
  }, [sections, query])

  return (
    <div className="space-y-1">
      <div className="relative mb-3">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
        <input
          aria-label="Hilfe durchsuchen"
          value={query}
          onChange={e => onQueryChange(e.target.value)}
          placeholder="Hilfe durchsuchen..."
          className="w-full pl-9 pr-3 py-2 bg-card border border-border rounded-lg text-xs text-text-primary outline-none focus:border-primary placeholder:text-text-muted"
        />
      </div>
      {filtered.map(section => (
        <div key={section.id}>
          <button
            onClick={() => toggle(section.id)}
            className="w-full flex items-center gap-2 px-2 py-1.5 text-xs font-semibold text-text-secondary hover:text-text-primary transition-colors"
          >
            {collapsed[section.id] ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
            {section.title}
          </button>
          {!collapsed[section.id] && (
            <div className="ml-4 space-y-0.5">
              {section.articles.map(article => (
                <button
                  key={article.id}
                  onClick={() => onSelect(article.id)}
                  className={`w-full text-left px-2 py-1 text-xs rounded transition-colors ${
                    activeArticle === article.id
                      ? 'bg-primary/15 text-primary font-medium'
                      : 'text-text-muted hover:text-text-primary hover:bg-card-alt'
                  }`}
                >
                  {article.title}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export default function Hilfe() {
  const location = useLocation()
  const [activeArticle, setActiveArticle] = useState(null)
  const [query, setQuery] = useState('')
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const contentRef = useRef(null)

  // Find article from hash
  useEffect(() => {
    const hash = location.hash?.slice(1)
    if (hash) {
      setActiveArticle(hash)
    } else if (!activeArticle) {
      setActiveArticle(HELP_SECTIONS[0]?.articles[0]?.id || null)
    }
  }, [location.hash])

  // Scroll to top when article changes
  useEffect(() => {
    contentRef.current?.scrollTo(0, 0)
  }, [activeArticle])

  const handleSelect = (id) => {
    setActiveArticle(id)
    setMobileNavOpen(false)
    window.history.replaceState(null, '', `/hilfe#${id}`)
  }

  // Find current article and its section
  let currentArticle = null
  let currentSection = null
  for (const section of HELP_SECTIONS) {
    const found = section.articles.find(a => a.id === activeArticle)
    if (found) {
      currentArticle = found
      currentSection = section
      break
    }
  }

  // Related articles (same section, excluding current)
  const related = currentSection?.articles.filter(a => a.id !== activeArticle).slice(0, 3) || []

  return (
    <div className="flex gap-4 min-h-[calc(100vh-120px)]">
      {/* Mobile toggle */}
      <button
        onClick={() => setMobileNavOpen(!mobileNavOpen)}
        className="md:hidden fixed bottom-4 right-4 z-40 p-3 bg-primary text-white rounded-full shadow-lg"
      >
        {mobileNavOpen ? <X size={20} /> : <Menu size={20} />}
      </button>

      {/* Sidebar */}
      <div className={`
        ${mobileNavOpen ? 'fixed inset-0 z-30 bg-body p-4 overflow-y-auto' : 'hidden'}
        md:block md:sticky md:top-4 md:self-start md:w-64 md:shrink-0 md:max-h-[calc(100vh-120px)] md:overflow-y-auto
      `}>
        <SidebarNav
          sections={HELP_SECTIONS}
          activeArticle={activeArticle}
          onSelect={handleSelect}
          query={query}
          onQueryChange={setQuery}
        />
      </div>

      {/* Content */}
      <div ref={contentRef} className="flex-1 min-w-0">
        {currentArticle ? (
          <div>
            {/* Breadcrumb */}
            <div className="text-xs text-text-secondary mb-4">
              <span>Hilfe</span>
              <span className="mx-1.5">/</span>
              <span>{currentSection?.title}</span>
              <span className="mx-1.5">/</span>
              <span className="text-text-secondary">{currentArticle.title}</span>
            </div>

            {/* Title */}
            <h2 className="text-lg font-semibold text-text-primary mb-2">{currentArticle.title}</h2>
            {currentArticle.summary && (
              <p className="text-sm text-primary font-medium mb-4">{currentArticle.summary}</p>
            )}

            {/* Content */}
            <div className="max-w-none">
              {renderContent(currentArticle.content)}
            </div>

            {/* Embed interactive glossary for the glossar article */}
            {activeArticle === 'glossar-link' && <Glossar />}

            {/* Related articles */}
            {related.length > 0 && (
              <div className="mt-6 pt-4 border-t border-border">
                <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-3">Verwandte Artikel</h4>
                <div className="flex flex-wrap gap-2">
                  {related.map(a => (
                    <button
                      key={a.id}
                      onClick={() => handleSelect(a.id)}
                      className="px-3 py-1.5 text-xs bg-card-alt text-text-secondary hover:text-text-primary rounded-md transition-colors"
                    >
                      {a.title}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="text-center text-text-muted py-20">
            <p className="text-sm">Wähle einen Artikel aus der Navigation.</p>
          </div>
        )}
      </div>
    </div>
  )
}
