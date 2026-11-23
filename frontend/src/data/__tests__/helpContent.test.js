import { describe, it, expect } from 'vitest'
import { HELP_SECTIONS, HELP_SECTION_META, HELP_CATEGORIES } from '../helpContent.js'
import { parseHelpArticle, buildHelpSections } from '../../lib/helpMarkdown.js'
import { helpCenterUrl } from '../../lib/helpCenter.js'

// Kapitel, Artikel-ID und Titel in Anzeige-Reihenfolge. Die IDs sind Linkziele
// (/hilfe#<id>, Verweise zwischen Artikeln, externe Seiten): eine ID faellt nie
// still weg. Neuer Artikel = neue Zeile hier.
const EXPECTED = [
  ["erste-schritte", "wichtiger-hinweis", "Wichtiger Hinweis"],
  ["erste-schritte", "willkommen", "Willkommen bei OpenFolio"],
  ["erste-schritte", "portfolio-einrichten", "Portfolio einrichten"],
  ["erste-schritte", "csv-import", "CSV-Import"],
  ["erste-schritte", "einstellungen", "Einstellungen konfigurieren"],
  ["portfolio-management", "portfolio-uebersicht", "Portfolio-Übersicht"],
  ["portfolio-management", "core-satellite", "Core/Satellite-System"],
  ["portfolio-management", "buckets", "Buckets — Portfolio-Segmentierung"],
  ["portfolio-management", "aktien-etfs", "Aktien & ETFs"],
  ["portfolio-management", "crypto", "Kryptowährungen"],
  ["portfolio-management", "edelmetalle", "Physische Edelmetalle"],
  ["portfolio-management", "cash-konti", "Cash & Konti"],
  ["portfolio-management", "vorsorge", "Vorsorge (3a/PK)"],
  ["portfolio-management", "immobilien", "Immobilien"],
  ["portfolio-management", "performance", "Performance verstehen"],
  ["portfolio-management", "transaktionen", "Transaktionen"],
  ["portfolio-management", "private-equity", "Direktbeteiligungen (Private Equity)"],
  ["portfolio-management", "dividenden", "Dividenden automatisch erfassen"],
  ["portfolio-management", "pending-orders", "Limit-Orders verwalten"],
  ["portfolio-management", "reports", "Report-Vault"],
  ["scoring-system", "wie-funktioniert-scoring", "Wie funktioniert das Scoring?"],
  ["scoring-system", "makro-gate", "Makro-Gate (7 Checks)"],
  ["scoring-system", "setup-score", "Setup-Score — technische Qualität"],
  ["scoring-system", "donchian-breakout", "Donchian Channel Breakout"],
  ["scoring-system", "branchenvergleich", "Branchenvergleich"],
  ["scoring-system", "signal-logik", "Signal-Logik"],
  ["marktanalyse", "marktklima", "Marktklima & Marktumfeld"],
  ["marktanalyse", "crash-indikatoren", "Crash-Indikatoren"],
  ["marktanalyse", "smart-money", "Smart Money Screening"],
  ["marktanalyse", "cot", "Commitments of Traders (COT)"],
  ["marktanalyse", "branchen-flow", "Branchen-Flow & Sektor-Rotation"],
  ["marktanalyse", "ch-makro", "Schweizer Makro-Übersicht"],
  ["aktien-analyse", "detailseite", "Detailseite verstehen"],
  ["aktien-analyse", "indikatoren", "Indikatoren erklärt"],
  ["aktien-analyse", "fundamental-karten", "Fundamental-Karten"],
  ["aktien-analyse", "mansfield-rs", "Mansfield Relative Stärke"],
  ["aktien-analyse", "eps-scanner", "EPS-Scanner"],
  ["risikomanagement", "stop-loss", "Stop-Loss Strategie"],
  ["risikomanagement", "schwur-1", "Schwur 1 (150-DMA Regel)"],
  ["risikomanagement", "alerts", "Alerts & Benachrichtigungen"],
  ["risikomanagement", "kauf-checklisten", "Kauf-Checklisten"],
  ["watchlist", "watchlist-nutzen", "Watchlist nutzen"],
  ["watchlist", "breakout-signale", "Breakout-Signale erkennen"],
  ["watchlist", "watchlist-zum-kauf", "Von der Watchlist zum Kauf"],
  ["glossar", "glossar-link", "Glossar der Finanzbegriffe"],
]

describe('helpContent', () => {
  it('laedt alle Artikel in der festgelegten Reihenfolge', () => {
    const actual = HELP_SECTIONS.flatMap((s) => s.articles.map((a) => [s.id, a.id, a.title]))
    expect(actual).toEqual(EXPECTED)
  })

  it('liefert je Artikel Summary und Inhalt', () => {
    for (const article of HELP_SECTIONS.flatMap((s) => s.articles)) {
      expect(article.summary, article.id).toBeTruthy()
      expect(article.content.trim(), article.id).toBeTruthy()
      expect(article.content, article.id).not.toMatch(/^---/)
    }
  })

  it('verweist intern nur auf vorhandene Artikel', () => {
    const ids = new Set(EXPECTED.map((row) => row[1]))
    for (const article of HELP_SECTIONS.flatMap((s) => s.articles)) {
      for (const m of article.content.matchAll(/\]\(#([^)]+)\)/g)) {
        expect(ids.has(m[1]), `${article.id} -> #${m[1]}`).toBe(true)
      }
    }
  })

  it('haelt Kapitel und Kategorien deckungsgleich', () => {
    expect(HELP_SECTIONS.map((s) => s.id)).toEqual(HELP_SECTION_META.map((s) => s.id))
    expect(Object.keys(HELP_CATEGORIES)).toEqual(HELP_SECTION_META.map((s) => s.id))
  })
})

describe('helpCenterUrl', () => {
  it('baut die Adresse aus Kapitel und Artikel', () => {
    expect(helpCenterUrl('erste-schritte', 'csv-import')).toBe('https://openfolio.cc/hilfe/erste-schritte/csv-import')
  })
})

describe('helpMarkdown', () => {
  const file = (fm, body = 'Text') => `---\n${fm}\n---\n\n${body}\n`
  const valid = 'id: "a"\ntitle: "A: mit Doppelpunkt"\nsummary: "S"\nsection: "x"\norder: 10'

  it('liest Frontmatter und Inhalt', () => {
    expect(parseHelpArticle(file(valid, 'Zeile 1\n\n## Titel'))).toEqual({
      id: 'a',
      title: 'A: mit Doppelpunkt',
      summary: 'S',
      section: 'x',
      order: 10,
      content: 'Zeile 1\n\n## Titel',
    })
  })

  it('liest Dateien mit Windows-Zeilenenden', () => {
    expect(parseHelpArticle(file(valid).replace(/\n/g, '\r\n')).content).toBe('Text')
  })

  it('bricht ohne Frontmatter oder Pflichtfeld ab', () => {
    expect(() => parseHelpArticle('Nur Text')).toThrow(/frontmatter block missing/)
    expect(() => parseHelpArticle(file('id: "a"\ntitle: "A"'))).toThrow(/"summary" missing/)
  })

  it('bricht bei unbekanntem Kapitel und doppelter ID ab', () => {
    const meta = [{ id: 'x', title: 'X', icon: 'Eye' }]
    expect(() => buildHelpSections(meta, { 'a.md': file(valid.replace('"x"', '"y"')) })).toThrow(/unknown section/)
    expect(() => buildHelpSections(meta, { 'a.md': file(valid), 'b.md': file(valid) })).toThrow(/duplicate article id/)
  })

  it('bricht bei order ohne Zahl und bei doppeltem order im Kapitel ab', () => {
    const meta = [{ id: 'x', title: 'X', icon: 'Eye' }]
    expect(() => parseHelpArticle(file(valid.replace('order: 10', 'order: 1o')))).toThrow(/"order" must be a number/)
    expect(() => parseHelpArticle(file(valid.replace('order: 10', 'order: "10"')))).toThrow(/"order" must be a number/)
    const twin = valid.replace('"a"', '"b"')
    expect(() => buildHelpSections(meta, { 'a.md': file(valid), 'b.md': file(twin) })).toThrow(/duplicate order 10/)
  })

  it('liest Trennzeilen mit Leerzeichen am Ende', () => {
    expect(parseHelpArticle(`--- \n${valid}\n---  \n\nText\n`).content).toBe('Text')
  })

  it('sortiert nach order, nicht nach Dateiname', () => {
    const second = valid.replace('"a"', '"b"').replace('order: 10', 'order: 5')
    const [section] = buildHelpSections([{ id: 'x', title: 'X', icon: 'Eye' }], { 'a.md': file(valid), 'z.md': file(second) })
    expect(section.articles.map((a) => a.id)).toEqual(['b', 'a'])
  })
})
