import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { lookupGlossary } from '../glossary.js'

const SRC = resolve(import.meta.dirname, '../..')

function collectFiles(dir) {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name)
    // __tests__ ausschliessen: diese Datei enthaelt selbst term="…"-Literale.
    if (statSync(full).isDirectory()) return name === '__tests__' ? [] : collectFiles(full)
    return /\.jsx?$/.test(name) ? [full] : []
  })
}

/** Alle im Frontend per <G term="…"> verwendeten Begriffe. */
function usedTerms() {
  const terms = new Set()
  for (const file of collectFiles(SRC)) {
    const src = readFileSync(file, 'utf8')
    for (const m of src.matchAll(/term="([^"]+)"/g)) terms.add(m[1])
  }
  return [...terms].sort()
}

describe('glossary coverage', () => {
  it('resolves every term used in the UI', () => {
    // Ein Tooltip ohne Eintrag faellt still aus — der Nutzer sieht nichts,
    // die Konsole meldet nichts. Deshalb der Test statt Sichtpruefung.
    const unresolved = usedTerms().filter((t) => lookupGlossary(t) === null)
    expect(unresolved).toEqual([])
  })

  it('finds terms regardless of hyphen or space spelling', () => {
    expect(lookupGlossary('Sharpe Ratio')?.key).toBe('Sharpe-Ratio')
    expect(lookupGlossary('Sharpe-Ratio')?.key).toBe('Sharpe-Ratio')
    expect(lookupGlossary('sortino ratio')?.key).toBe('Sortino-Ratio')
    expect(lookupGlossary('Calmar Ratio')?.key).toBe('Calmar-Ratio')
  })

  it('returns null for unknown terms', () => {
    expect(lookupGlossary('Nicht Existierender Begriff')).toBe(null)
    expect(lookupGlossary('')).toBe(null)
    expect(lookupGlossary(null)).toBe(null)
  })
})
