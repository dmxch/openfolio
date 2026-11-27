import { describe, it, expect } from 'vitest'
import { isSaronStale, SARON_STALE_DAYS } from '../ImmobilienWidget'

const at = (iso) => new Date(iso).getTime()

describe('isSaronStale', () => {
  it('warnt nicht im regulären Wochenrhythmus der SNB', () => {
    // Wert vom Freitag, angesehen am Freitag und am Montag der Folgewoche.
    expect(isSaronStale('2026-11-20', at('2026-11-27T19:00:00Z'))).toBe(false)
    expect(isSaronStale('2026-11-20', at('2026-11-30T09:00:00Z'))).toBe(false)
  })

  it('warnt, wenn eine ganze Veröffentlichung fehlt', () => {
    expect(SARON_STALE_DAYS).toBe(14)
    expect(isSaronStale('2026-11-20', at('2026-12-04T00:00:00Z'))).toBe(false)
    expect(isSaronStale('2026-11-20', at('2026-12-05T00:00:00Z'))).toBe(true)
  })

  it('warnt nicht ohne oder mit kaputtem Datum', () => {
    expect(isSaronStale(null)).toBe(false)
    expect(isSaronStale('kein Datum')).toBe(false)
  })
})
