import { describe, it, expect, beforeEach } from 'vitest'
import {
  configureFormats,
  formatCHF,
  formatCHFExact,
  formatPct,
  formatNumber,
  formatDate,
  formatDateTime,
  pnlColor,
  climateColor,
  climateBg,
} from '../format.js'

// Reset to default CH locale before each test
beforeEach(() => {
  configureFormats({ number_format: 'ch', date_format: 'dd.mm.yyyy' })
})

// --- formatCHF ---
describe('formatCHF', () => {
  it('formats positive values with CHF prefix', () => {
    const result = formatCHF(1234)
    expect(result).toMatch(/^CHF\s/)
    expect(result).toContain('1')
  })

  it('formats negative values with minus sign', () => {
    const result = formatCHF(-500)
    expect(result).toMatch(/^CHF -/)
  })

  it('returns dash for null/undefined', () => {
    expect(formatCHF(null)).toBe('\u2013')
    expect(formatCHF(undefined)).toBe('\u2013')
  })

  it('respects decimals option', () => {
    const result = formatCHF(1234.567, { decimals: 2 })
    expect(result).toContain('234.57') // rounded
  })

  it('formats zero correctly', () => {
    const result = formatCHF(0)
    expect(result).toMatch(/^CHF\s+0$/)
  })
})

// --- formatCHFExact (deprecated wrapper) ---
describe('formatCHFExact', () => {
  it('formats with 2 decimal places', () => {
    const result = formatCHFExact(100)
    expect(result).toContain('100.00')
  })
})

// --- formatPct ---
describe('formatPct', () => {
  it('formats positive with plus sign', () => {
    expect(formatPct(12.345)).toBe('+12.35%')
  })

  it('formats negative without plus sign', () => {
    expect(formatPct(-3.5)).toBe('-3.50%')
  })

  it('formats zero without plus sign', () => {
    expect(formatPct(0)).toBe('0.00%')
  })

  it('returns dash for null', () => {
    expect(formatPct(null)).toBe('\u2013')
  })
})

// --- formatNumber ---
describe('formatNumber', () => {
  it('returns dash for null', () => {
    expect(formatNumber(null)).toBe('\u2013')
  })

  it('formats with specified decimals', () => {
    const result = formatNumber(1234.5, 2)
    // CH locale uses apostrophe as thousands separator
    expect(result).toContain('234.50')
  })
})

// --- formatDate ---
describe('formatDate', () => {
  it('returns dash for empty input', () => {
    expect(formatDate(null)).toBe('\u2013')
    expect(formatDate('')).toBe('\u2013')
  })

  it('formats date in dd.mm.yyyy (default CH)', () => {
    const result = formatDate('2024-06-15')
    // CH locale: 15.6.2024 or 15.06.2024
    expect(result).toMatch(/15/)
    expect(result).toMatch(/2024/)
  })

  it('formats date in yyyy-mm-dd when configured', () => {
    configureFormats({ date_format: 'yyyy-mm-dd' })
    const result = formatDate('2024-06-15')
    expect(result).toBe('2024-06-15')
  })
})

// --- formatDateTime ---
describe('formatDateTime', () => {
  it('returns dash for empty input', () => {
    expect(formatDateTime(null)).toBe('\u2013')
  })

  it('includes time component', () => {
    const result = formatDateTime('2024-06-15T14:30:00')
    expect(result).toContain('14')
    expect(result).toContain('30')
  })
})

// --- configureFormats ---
describe('configureFormats', () => {
  it('switches to EN locale', () => {
    configureFormats({ number_format: 'en' })
    const result = formatNumber(1234567, 0)
    // EN uses comma as thousands separator
    expect(result).toContain('1,234,567')
  })

  it('ignores invalid locale', () => {
    configureFormats({ number_format: 'xx' })
    // Should remain CH (no crash)
    const result = formatNumber(1000)
    expect(result).toBeTruthy()
  })
})

// --- pnlColor ---
describe('pnlColor', () => {
  it('returns success for positive', () => {
    expect(pnlColor(10)).toBe('text-success')
  })

  it('returns danger for negative', () => {
    expect(pnlColor(-5)).toBe('text-danger')
  })

  it('returns secondary for zero', () => {
    expect(pnlColor(0)).toBe('text-text-secondary')
  })
})

// --- climateColor ---
describe('climateColor', () => {
  it('returns success for bullish', () => {
    expect(climateColor('bullish')).toBe('text-success')
  })

  it('returns danger for bearish', () => {
    expect(climateColor('bearish')).toBe('text-danger')
  })

  it('returns warning for neutral/other', () => {
    expect(climateColor('neutral')).toBe('text-warning')
  })
})

// --- climateBg ---
describe('climateBg', () => {
  it('returns success bg for bullish', () => {
    expect(climateBg('bullish')).toContain('bg-success')
  })

  it('returns danger bg for bearish', () => {
    expect(climateBg('bearish')).toContain('bg-danger')
  })

  it('returns warning bg for neutral', () => {
    expect(climateBg('neutral')).toContain('bg-warning')
  })
})
