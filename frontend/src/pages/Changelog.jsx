import { useState, useEffect } from 'react'
import { FileText } from 'lucide-react'

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

const sectionColors = {
  'Hinzugefügt': 'text-green-400',
  'Behoben': 'text-blue-400',
  'Geändert': 'text-yellow-400',
  'Entfernt': 'text-red-400',
  'Sicherheit': 'text-orange-400',
}

const sectionBadgeColors = {
  'Hinzugefügt': 'bg-green-500/10 text-green-400 border-green-500/20',
  'Behoben': 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  'Geändert': 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
  'Entfernt': 'bg-red-500/10 text-red-400 border-red-500/20',
  'Sicherheit': 'bg-orange-500/10 text-orange-400 border-orange-500/20',
}

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
      <div className="max-w-3xl mx-auto">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-card-alt rounded w-48" />
          <div className="h-4 bg-card-alt rounded w-full" />
          <div className="h-4 bg-card-alt rounded w-3/4" />
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <FileText size={24} className="text-primary" />
        <h1 className="text-2xl font-bold text-text-primary">Changelog</h1>
      </div>
      <p className="text-sm text-text-secondary mb-8">
        Alle wichtigen Änderungen an OpenFolio — gruppiert nach Version.
      </p>

      {versions.length === 0 && (
        <p className="text-text-muted text-sm">Keine Changelog-Einträge gefunden.</p>
      )}

      <div className="space-y-8">
        {versions.map(v => (
          <div key={v.version} className="bg-card border border-border rounded-xl p-6">
            <div className="flex items-baseline gap-3 mb-4">
              <h2 className="text-lg font-bold text-text-primary">v{v.version}</h2>
              <span className="text-sm text-text-muted">{v.date}</span>
            </div>
            <div className="space-y-4">
              {v.sections.map(s => (
                <div key={s.title}>
                  <span className={`inline-block text-xs font-medium px-2 py-0.5 rounded border mb-2 ${sectionBadgeColors[s.title] || 'bg-card-alt text-text-secondary border-border'}`}>
                    {s.title}
                  </span>
                  <ul className="space-y-1.5 ml-1">
                    {s.items.map((item, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-text-secondary">
                        <span className={`mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 ${sectionColors[s.title] ? sectionColors[s.title].replace('text-', 'bg-') : 'bg-text-muted'}`} />
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
