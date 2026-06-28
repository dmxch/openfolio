import { useState, useEffect } from 'react'
import PageHeader from '../components/ui/PageHeader'
import Card from '../components/ui/Card'

function parseChangelog(text) {
  const versions = []
  const versionRegex = /^## \[(.+?)\] — (.+)$/gm
  let match
  const matches = []

  while ((match = versionRegex.exec(text)) !== null) {
    matches.push({ version: match[1], date: match[2], index: match.index })
  }

  for (let i = 0; i < matches.length; i++) {
    const start = matches[i].index
    const end = i + 1 < matches.length ? matches[i + 1].index : text.length
    const block = text.slice(start, end)

    const sections = []
    const sectionRegex = /^### (.+)$/gm
    let sMatch
    const sMatches = []

    while ((sMatch = sectionRegex.exec(block)) !== null) {
      sMatches.push({ title: sMatch[1], index: sMatch.index })
    }

    for (let j = 0; j < sMatches.length; j++) {
      const sStart = sMatches[j].index + sMatches[j].title.length + 5
      const sEnd = j + 1 < sMatches.length ? sMatches[j + 1].index : block.length
      const items = block.slice(sStart, sEnd)
        .split('\n')
        .map(l => l.replace(/^- /, '').trim())
        .filter(l => l.length > 0)
      sections.push({ title: sMatches[j].title, items })
    }

    versions.push({ version: matches[i].version, date: matches[i].date, sections })
  }

  return versions
}

const sectionStyles = {
  'Hinzugefügt': { badge: 'bg-success/10 text-success border-success/25', dot: '#45c08a' },
  'Behoben': { badge: 'bg-primary/10 text-primary border-primary/30', dot: '#5b8def' },
  'Geändert': { badge: 'bg-warning/10 text-warning border-warning/30', dot: '#e0a64b' },
  'Entfernt': { badge: 'bg-danger/10 text-danger border-danger/30', dot: '#e8625a' },
  'Sicherheit': { badge: 'bg-warning/10 text-warning border-warning/30', dot: '#e0a64b' },
}

const defaultStyle = { badge: 'bg-table-head text-text-secondary border-border', dot: '#7a8698' }

export default function Changelog() {
  const [versions, setVersions] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/changelog.md')
      .then(r => r.text())
      .then(text => {
        setVersions(parseChangelog(text))
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="pb-10">
        <PageHeader title="Changelog" subtitle="Versionsverlauf" showBell={false} />
        <div className="flex flex-col gap-[18px]">
          <div className="bg-card border border-border rounded-card p-6 animate-pulse space-y-4">
            <div className="h-6 w-44 rounded bg-hover" />
            <div className="h-4 w-full rounded bg-hover" />
            <div className="h-4 w-3/4 rounded bg-hover" />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="pb-10">
      <PageHeader title="Changelog" subtitle="Versionsverlauf" showBell={false} />
      <div className="flex flex-col gap-[18px]">
        <p className="text-sm text-text-secondary">
          Alle wichtigen Änderungen an OpenFolio — gruppiert nach Version.
        </p>

        {versions.length === 0 && (
          <Card className="px-[18px] py-4">
            <p className="text-sm text-text-muted">Keine Changelog-Einträge gefunden.</p>
          </Card>
        )}

        {versions.map(v => (
          <Card key={v.version} className="overflow-hidden">
            <div className="px-[18px] py-4 border-b border-border-2 flex items-baseline gap-3">
              <h2 className="text-sm font-semibold text-text-primary">v{v.version}</h2>
              <span className="font-mono text-[11.5px] text-text-faint">{v.date}</span>
            </div>
            <div className="px-[18px] py-4 flex flex-col gap-4">
              {v.sections.map(s => {
                const st = sectionStyles[s.title] || defaultStyle
                return (
                  <div key={s.title}>
                    <span className={`inline-block mb-2 rounded border px-2 py-0.5 text-[11px] font-medium ${st.badge}`}>
                      {s.title}
                    </span>
                    <ul className="ml-1 space-y-1.5">
                      {s.items.map((item, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-text-secondary">
                          <span
                            className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
                            style={{ background: st.dot }}
                          />
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                )
              })}
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
