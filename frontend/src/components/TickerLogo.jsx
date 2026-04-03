import { useState } from 'react'

const LOGO_CDN = 'https://assets.parqet.com/logos/symbol/'

function initialsColor(ticker) {
  let hash = 0
  for (let i = 0; i < ticker.length; i++) hash = ticker.charCodeAt(i) + ((hash << 5) - hash)
  const colors = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#06B6D4', '#6366F1']
  return colors[Math.abs(hash) % colors.length]
}

export default function TickerLogo({ ticker, size = 20 }) {
  const [failed, setFailed] = useState(false)

  if (failed || !ticker) {
    return (
      <span
        className="inline-flex items-center justify-center rounded-full text-white font-bold shrink-0"
        style={{ width: size, height: size, fontSize: size * 0.4, backgroundColor: initialsColor(ticker || '') }}
      >
        {(ticker || '?')[0]}
      </span>
    )
  }

  return (
    <img
      src={`${LOGO_CDN}${ticker}`}
      alt=""
      width={size}
      height={size}
      className="rounded-full object-contain shrink-0"
      style={{ width: size, height: size }}
      onError={() => setFailed(true)}
      loading="lazy"
    />
  )
}
