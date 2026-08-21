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

  it('maps crypto USD pairs to the CRYPTO index (hyphen would be a TV spread)', () => {
    expect(toTradingViewSymbol('BTC-USD')).toBe('CRYPTO:BTCUSD')
    expect(toTradingViewSymbol('ETH-USD')).toBe('CRYPTO:ETHUSD')
    expect(toTradingViewSymbol('SOL-USD')).toBe('CRYPTO:SOLUSD')
  })

  it('maps stablecoin pairs to Binance', () => {
    expect(toTradingViewSymbol('BTC-USDT')).toBe('BINANCE:BTCUSDT')
    expect(toTradingViewSymbol('BTC-USDC')).toBe('BINANCE:BTCUSDC')
  })

  it('maps EUR/GBP pairs to Coinbase', () => {
    expect(toTradingViewSymbol('BTC-EUR')).toBe('COINBASE:BTCEUR')
    expect(toTradingViewSymbol('BTC-GBP')).toBe('COINBASE:BTCGBP')
  })

  it('maps crypto cross pairs to Binance', () => {
    expect(toTradingViewSymbol('ETH-BTC')).toBe('BINANCE:ETHBTC')
    expect(toTradingViewSymbol('SOL-ETH')).toBe('BINANCE:SOLETH')
  })

  it('maps class shares to dot notation', () => {
    expect(toTradingViewSymbol('BRK-B')).toBe('BRK.B')
    expect(toTradingViewSymbol('BF-B')).toBe('BF.B')
  })

  it('leaves cash/pension account labels untouched', () => {
    expect(toTradingViewSymbol('CASH-USD')).toBe('CASH-USD')
    expect(toTradingViewSymbol('CASH-CHF')).toBe('CASH-CHF')
    expect(toTradingViewSymbol('PENSION-CHF')).toBe('PENSION-CHF')
  })

  it('returns null/undefined unchanged', () => {
    expect(toTradingViewSymbol(null)).toBe(null)
    expect(toTradingViewSymbol(undefined)).toBe(undefined)
  })

  it('returns empty string unchanged', () => {
    expect(toTradingViewSymbol('')).toBe('')
  })
})
