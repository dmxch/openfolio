// @vitest-environment node
//
// Statische Pruefung von frontend/nginx.conf. Ein laufender nginx steht in der
// Test-Umgebung nicht zur Verfuegung; diese Tests halten fest, was die Datei
// zusichern muss, und fallen bei einem Rueckbau auf.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const read = (rel) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf-8')

// Kommentare entfernen: geprueft wird die wirksame Konfiguration.
const CONF = read('../../nginx.conf')
  .split('\n')
  .filter((line) => !line.trim().startsWith('#'))
  .join('\n')

/** Inhalt des ersten Blocks, dessen Kopf auf `head` passt (ohne Verschachtelung). */
function block(head) {
  const start = CONF.search(head)
  expect(start, `Block ${head} fehlt`).toBeGreaterThanOrEqual(0)
  const open = CONF.indexOf('{', start)
  let depth = 1
  let i = open + 1
  for (; depth > 0 && i < CONF.length; i += 1) {
    if (CONF[i] === '{') depth += 1
    if (CONF[i] === '}') depth -= 1
  }
  return CONF.slice(open + 1, i - 1)
}

// Loopback und private Netze (RFC 1918, ULA). Nur ihnen darf nginx glauben.
const PRIVATE_NETS = ['127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '::1/128', 'fc00::/7']

// --- K097: jeder Client hat sein eigenes Budget ---
describe('nginx.conf: echte Client-IP', () => {
  const trusted = [...CONF.matchAll(/^\s*set_real_ip_from\s+(\S+);/gm)].map((m) => m[1])

  it('schluesselt die limit_req-Zone auf die Client-IP statt auf die Proxy-Adresse', () => {
    const zone = CONF.match(/limit_req_zone\s+(\S+)\s+zone=api/)
    expect(zone[1]).toBe('$client_real_ip')
    expect(CONF).not.toContain('$binary_remote_addr')
  })

  it('glaubt X-Forwarded-For nur von Loopback und privaten Netzen', () => {
    expect(trusted.length).toBeGreaterThan(0)
    expect(trusted.filter((net) => !PRIVATE_NETS.includes(net))).toEqual([])
    expect(CONF).toMatch(/^\s*real_ip_header\s+X-Forwarded-For;/m)
  })

  it('nimmt den rechten X-Forwarded-For-Eintrag (ein Hop, wie das Backend)', () => {
    expect(CONF).toMatch(/^\s*real_ip_recursive\s+off;/m)
  })

  it('fuehrt fuer CF-Connecting-IP dieselbe Liste vertrauter Absender', () => {
    const geo = block(/geo\s+\$realip_remote_addr\s+\$peer_is_trusted_proxy/)
    const entries = [...geo.matchAll(/^\s*(\S+)\s+(\S+);/gm)].map((m) => [m[1], m[2]])
    expect(entries.filter(([net]) => net === 'default')).toEqual([['default', '0']])
    const nets = entries.filter(([net]) => net !== 'default')
    expect(nets.every(([, value]) => value === '1')).toBe(true)
    expect(nets.map(([net]) => net).sort()).toEqual([...trusted].sort())
  })

  describe('CF-Connecting-IP', () => {
    // Wertet den Schluessel so aus wie nginx: erste passende Regex, sonst default.
    const resolve = (trustedPeer, xff, cf) => {
      const map = block(/map\s+"\$peer_is_trusted_proxy\|\$http_x_forwarded_for\|\$http_cf_connecting_ip"\s+\$client_real_ip/)
      const rules = [...map.matchAll(/^\s*(\S+)\s+(\S+);/gm)].map((m) => [m[1], m[2]])
      const key = `${trustedPeer ? 1 : 0}|${xff}|${cf}`
      for (const [pattern, value] of rules) {
        if (!pattern.startsWith('"~')) continue
        const m = key.match(new RegExp(pattern.slice(2, -1)))
        if (m) return value === '$cf_connecting_ip' ? m.groups.cf_connecting_ip : value
      }
      return rules.find(([pattern]) => pattern === 'default')[1]
    }

    it('gilt, wenn ein vertrauter Absender kein X-Forwarded-For mitgibt', () => {
      expect(resolve(true, '', '203.0.113.7')).toBe('203.0.113.7')
      expect(resolve(true, '', '2001:db8::7')).toBe('2001:db8::7')
    })

    it('gilt nicht von einem fremden Absender', () => {
      expect(resolve(false, '', '203.0.113.7')).toBe('$remote_addr')
    })

    it('weicht dem X-Forwarded-For des vorgelagerten Proxys', () => {
      // Ein Proxy ohne Cloudflare reicht den Header des Clients durch.
      expect(resolve(true, '198.51.100.4', '203.0.113.7')).toBe('$remote_addr')
      expect(resolve(true, '::1', '203.0.113.7')).toBe('$remote_addr')
      expect(resolve(true, '6.6.6.6, 198.51.100.4', '203.0.113.7')).toBe('$remote_addr')
    })

    it('gilt nur als IP-Adresse', () => {
      expect(resolve(true, '', 'evil key')).toBe('$remote_addr')
      expect(resolve(true, '', '')).toBe('$remote_addr')
      expect(resolve(true, '|', '203.0.113.7')).toBe('$remote_addr')
    })
  })

  it('reicht dem Backend genau einen Wert als Client-IP weiter', () => {
    const api = block(/location\s+\/api\/\s*\{/)
    expect(api).toMatch(/proxy_set_header\s+X-Forwarded-For\s+\$client_real_ip;/)
    expect(api).toMatch(/proxy_set_header\s+X-Real-IP\s+\$client_real_ip;/)
    expect(api).not.toContain('$proxy_add_x_forwarded_for')
  })
})

// --- K168: die CSP laesst keine beliebigen Bild- und Verbindungsziele zu ---
describe('nginx.conf: Content-Security-Policy der App', () => {
  const directive = (name) => {
    const csp = CONF.match(/add_header Content-Security-Policy "(default-src 'self';[^"]+)" always;/)[1]
    return csp.split(';').map((d) => d.trim().split(/\s+/)).find(([key]) => key === name).slice(1)
  }

  it('erlaubt Bilder nur von der eigenen Origin, als data: und vom Logo-Host', () => {
    const logoHost = new URL(read('../components/TickerLogo.jsx').match(/LOGO_CDN = '([^']+)'/)[1]).origin
    expect(directive('img-src').sort()).toEqual(["'self'", 'data:', logoHost].sort())
  })

  it('erlaubt Verbindungen nur zur eigenen API und zu TradingView', () => {
    expect(directive('connect-src').sort()).toEqual(["'self'", 'https://*.tradingview.com'].sort())
  })

  it('behaelt den TradingView-Loader in script-src ohne unsafe-Quellen', () => {
    expect(directive('script-src')).toEqual(["'self'", 'https://s3.tradingview.com'])
  })
})

// --- K143: index.html wird revalidiert, changelog.md ist typisiert und komprimiert ---
describe('nginx.conf: Auslieferung statischer Dateien', () => {
  it('setzt fuer index.html no-cache, ohne die Security-Header zu kappen', () => {
    const index = block(/location\s+=\s+\/index\.html\s*\{/)
    expect(index).toMatch(/expires\s+-1;/)
    expect(index).not.toContain('add_header')
  })

  it('liefert changelog.md als text/markdown mit gzip', () => {
    const changelog = block(/location\s+=\s+\/changelog\.md\s*\{/)
    expect(changelog).toMatch(/default_type\s+text\/markdown;/)
    expect(changelog).toMatch(/charset_types\s+text\/markdown;/)
    expect(changelog).not.toContain('add_header')
    expect(CONF.match(/gzip_types\s+([^;]+);/)[1].split(/\s+/)).toContain('text/markdown')
  })
})
