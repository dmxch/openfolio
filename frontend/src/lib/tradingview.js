/**
 * Maps yfinance ticker suffixes to TradingView exchange prefixes.
 */
const TV_EXCHANGE_MAP = {
  '.SW': 'SIX', '.L': 'LSE', '.AS': 'AMS', '.DE': 'XETR',
  '.PA': 'EPA', '.MI': 'MIL', '.TO': 'TSX', '.V': 'TSXV',
  '.HK': 'HKEX', '.T': 'TSE', '.AX': 'ASX',
}

/**
 * Converts a yfinance ticker to TradingView symbol format.
 * e.g. "NOVN.SW" → "SIX:NOVN", "AAPL" → "AAPL"
 */
export function toTradingViewSymbol(yfinanceTicker) {
  if (!yfinanceTicker) return yfinanceTicker
  for (const [suffix, exchange] of Object.entries(TV_EXCHANGE_MAP)) {
    if (yfinanceTicker.endsWith(suffix)) {
      return `${exchange}:${yfinanceTicker.slice(0, -suffix.length)}`
    }
  }
  return yfinanceTicker
}
