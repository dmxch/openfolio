/**
 * Maps yfinance ticker suffixes to TradingView exchange prefixes.
 */
const TV_EXCHANGE_MAP = {
  '.SW': 'SIX', '.L': 'LSE', '.AS': 'AMS', '.DE': 'XETR',
  '.PA': 'EPA', '.MI': 'MIL', '.TO': 'TSX', '.V': 'TSXV',
  '.HK': 'HKEX', '.T': 'TSE', '.AX': 'ASX',
}

/**
 * Crypto quote pairs in yfinance/CoinGecko style (BTC-USD, ETH-EUR, SOL-USDT).
 *
 * TradingView reads a hyphen as a spread operator: "BTC-USD" charts the
 * Grayscale BTC trust MINUS the dollar index, which is why the price scale
 * showed negative values instead of the Bitcoin price. Every pair therefore
 * needs an explicit exchange-prefixed symbol.
 *
 * Longest suffix first so "-USDT"/"-USDC" win over "-USD".
 * Exchange choice verified against tradingview.com/symbols/:
 * CRYPTO: carries the USD index pairs but no EUR/USDT pairs.
 */
const TV_CRYPTO_QUOTE_MAP = [
  ['-USDT', 'BINANCE', 'USDT'],
  ['-USDC', 'BINANCE', 'USDC'],
  ['-USD', 'CRYPTO', 'USD'],
  ['-EUR', 'COINBASE', 'EUR'],
  ['-GBP', 'COINBASE', 'GBP'],
  ['-BTC', 'BINANCE', 'BTC'],
  ['-ETH', 'BINANCE', 'ETH'],
]

// Konto-Labels (CASH-CHF, PENSION-…), keine handelbaren Symbole — nie mappen.
const NON_MARKET_PREFIXES = ['CASH-', 'PENSION-']

const CRYPTO_BASE_RE = /^[A-Z0-9]{2,10}$/

/**
 * Converts a yfinance ticker to TradingView symbol format.
 * e.g. "NOVN.SW" → "SIX:NOVN", "BTC-USD" → "CRYPTO:BTCUSD",
 *      "BRK-B" → "BRK.B", "AAPL" → "AAPL"
 */
export function toTradingViewSymbol(yfinanceTicker) {
  if (!yfinanceTicker) return yfinanceTicker
  for (const [suffix, exchange] of Object.entries(TV_EXCHANGE_MAP)) {
    if (yfinanceTicker.endsWith(suffix)) {
      return `${exchange}:${yfinanceTicker.slice(0, -suffix.length)}`
    }
  }

  const upper = yfinanceTicker.toUpperCase()
  if (NON_MARKET_PREFIXES.some(p => upper.startsWith(p))) return yfinanceTicker

  for (const [suffix, exchange, quote] of TV_CRYPTO_QUOTE_MAP) {
    if (upper.endsWith(suffix)) {
      const base = upper.slice(0, -suffix.length)
      if (CRYPTO_BASE_RE.test(base)) return `${exchange}:${base}${quote}`
    }
  }

  // Klasse-Shares: yfinance schreibt BRK-B, TradingView BRK.B — der Bindestrich
  // wäre sonst ebenfalls eine Subtraktion.
  if (/^[A-Z]{1,5}-[A-Z]$/.test(upper)) return upper.replace('-', '.')

  return yfinanceTicker
}
