import { describe, it, expect } from 'vitest'
import { toTradingViewSymbol } from '../tradingview.js'

describe('toTradingViewSymbol', () => {
  it('maps .SW to SIX exchange', () => {
    expect(toTradingViewSymbol('NOVN.SW')).toBe('SIX:NOVN')
  })

  it('maps .L to LSE exchange', () => {
    expect(toTradingViewSymbol('SHEL.L')).toBe('LSE:SHEL')
  })

  it('maps .DE to XETR exchange', () => {
    expect(toTradingViewSymbol('SAP.DE')).toBe('XETR:SAP')
  })

  it('maps .PA to EPA exchange', () => {
    expect(toTradingViewSymbol('MC.PA')).toBe('EPA:MC')
  })

  it('maps .AS to AMS exchange', () => {
    expect(toTradingViewSymbol('ASML.AS')).toBe('AMS:ASML')
  })

  it('maps .MI to MIL exchange', () => {
    expect(toTradingViewSymbol('ISP.MI')).toBe('MIL:ISP')
  })

  it('maps .TO to TSX exchange', () => {
    expect(toTradingViewSymbol('RY.TO')).toBe('TSX:RY')
  })

  it('maps .V to TSXV exchange', () => {
    expect(toTradingViewSymbol('ABC.V')).toBe('TSXV:ABC')
  })

  it('maps .HK to HKEX exchange', () => {
    expect(toTradingViewSymbol('0700.HK')).toBe('HKEX:0700')
  })

  it('maps .T to TSE exchange', () => {
    expect(toTradingViewSymbol('7203.T')).toBe('TSE:7203')
  })

  it('maps .AX to ASX exchange', () => {
    expect(toTradingViewSymbol('BHP.AX')).toBe('ASX:BHP')
  })

  it('returns US tickers unchanged', () => {
    expect(toTradingViewSymbol('AAPL')).toBe('AAPL')
    expect(toTradingViewSymbol('MSFT')).toBe('MSFT')
  })

  it('returns null/undefined unchanged', () => {
    expect(toTradingViewSymbol(null)).toBe(null)
    expect(toTradingViewSymbol(undefined)).toBe(undefined)
  })

  it('returns empty string unchanged', () => {
    expect(toTradingViewSymbol('')).toBe('')
  })
})
