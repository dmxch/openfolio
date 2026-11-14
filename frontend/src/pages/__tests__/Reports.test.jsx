import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import Reports from '../Reports'

// Stabile Objekte: ReportViewer haengt einen Effekt an `data`; ein neues Objekt
// je Render liefe in eine Endlosschleife.
const api = vi.hoisted(() => {
  const state = { body: '' }
  const list = {
    data: {
      results: [{ id: 7, title: 'Wochenbericht', category: 'macro', tags: [] }],
      categories: [],
      all_tags: [],
      total: 1,
    },
    loading: false,
    error: null,
    refetch: () => {},
  }
  const detail = { loading: false, error: null, data: null }
  return { state, list, detail }
})

vi.mock('../../hooks/useApi', () => ({
  useApi: (endpoint) => {
    if (endpoint.startsWith('/reports?')) return api.list
    if (!api.detail.data || api.detail.data.body !== api.state.body) {
      api.detail.data = { id: 7, title: 'Wochenbericht', category: 'macro', tags: [], body: api.state.body }
    }
    return api.detail
  },
  authFetch: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}))

vi.mock('../../components/Toast', () => ({ useToast: () => () => {} }))

function renderReport(body) {
  api.state.body = body
  return render(<Reports />)
}

afterEach(cleanup)

// K168: Ein Report kommt per API-Key von aussen. Ein <img> mit fremder URL
// wuerde dem Host beim Oeffnen IP und Zeitpunkt melden.
describe('Report-Viewer: Bilder im Markdown', () => {
  it('laedt ein externes Bild nicht, sondern zeigt es als Link', () => {
    const { container } = renderReport('Text davor\n\n![Kursverlauf](https://tracker.example/p.png)\n')

    expect(container.querySelector('img')).toBeNull()
    const link = screen.getByRole('link', { name: 'Bild: Kursverlauf' })
    expect(link.getAttribute('href')).toBe('https://tracker.example/p.png')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toBe('noopener noreferrer')
  })

  it('nennt die Adresse, wenn das Bild keinen Alt-Text hat', () => {
    const { container } = renderReport('![](https://tracker.example/pixel.gif)')

    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByRole('link', { name: 'Bild: https://tracker.example/pixel.gif' })).toBeTruthy()
  })

  it('laedt auch Bilder der eigenen Origin und in Tabellen nicht', () => {
    const { container } = renderReport('| A |\n|---|\n| ![x](/api/reports/1/export) |\n')

    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByRole('link', { name: 'Bild: x' }).getAttribute('href')).toBe('/api/reports/1/export')
  })

  it('rendert gewoehnliche Links und Text weiter', () => {
    renderReport('Siehe [Quelle](https://example.org/a) und **fett**.')

    expect(screen.getByRole('link', { name: 'Quelle' }).getAttribute('href')).toBe('https://example.org/a')
    expect(screen.getByText('fett').tagName).toBe('STRONG')
  })
})
