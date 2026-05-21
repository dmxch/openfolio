// Geteilte Konfiguration zwischen /screening und /smart-money.
// Aus pages/Screening.jsx extrahiert, damit beide Pages aus derselben Quelle lesen.
//
// HINWEIS: Icon-Werte sind React-Components (Lucide). Render in der Komponente
// macht die jeweilige Page selbst, hier liegt nur das Mapping.

import { Users, User, TrendingDown, Building2, BarChart3, AlertTriangle, Flag } from 'lucide-react'

export const SIGNAL_CONFIG = {
  insider_cluster: { label: 'Insider-Cluster', glossar: 'Insider-Cluster', short: 'I', icon: Users, description: 'Mehrere Insider kaufen gleichzeitig', type: 'positive', weight: 3 },
  large_buy: { label: 'Grosser Insider-Kauf', glossar: 'Grosser Insider-Kauf', short: 'I', icon: Users, description: 'Insider-Kauf > $500k', type: 'positive', weight: 1 },
  superinvestor: { label: 'Superinvestor', glossar: 'Superinvestor', short: 'A', icon: Users, description: 'Buffett, Icahn, Ackman etc. halten Position', type: 'positive', weight: 2 },
  activist: { label: 'Aktivist (13D/13G)', glossar: 'Aktivist (13D/13G)', short: 'A', icon: Users, description: 'Aktivist mit 5%+ Beteiligung (SEC Filing)', type: 'positive', weight: 2 },
  buyback: { label: 'Aktienrückkauf', glossar: 'Aktienrückkauf', short: 'B', icon: Building2, description: '8-K Rückkaufprogramm angekündigt', type: 'positive', weight: 2 },
  congressional: { label: 'Kongresskauf', glossar: 'Kongresskauf', short: 'C', icon: Building2, description: 'US-Kongressmitglied hat gekauft', type: 'positive', weight: 1 },
  short_trend: { label: 'Short-Trend', glossar: 'Short-Trend', short: 'S', icon: TrendingDown, description: 'Short-Ratio stark gestiegen — Warnsignal (−1 Punkt)', type: 'warning', weight: -1 },
  ftd: { label: 'Fails-to-Deliver', glossar: 'Fails-to-Deliver', short: 'F', icon: AlertTriangle, description: 'Hohe Anzahl nicht gelieferter Aktien — Warnsignal (−1 Punkt)', type: 'warning', weight: -1 },
  unusual_volume: { label: 'Unusual Volume', glossar: 'Unusual Volume', short: 'V', icon: BarChart3, description: 'Volumen > 3× Durchschnitt — indikativ, kein Score-Einfluss', type: 'flag', weight: 0 },
  superinvestor_13f_single: { label: '13F Einzelfonds', glossar: '13F Einzelfonds', short: 'F1', icon: User, description: 'SEC 13F: Einzelner getrackter Fonds hat Position verändert (informativ, Konsens-Prüfung ausstehend)', type: 'positive', weight: 1 },
  superinvestor_13f_consensus: { label: '13F Konsens', glossar: '13F Konsens', short: 'FC', icon: Users, description: 'SEC 13F Q/Q-Konsens: Mindestens 3 getrackte Fonds mit gleicher Positions-Änderung (Quartal aggregations-bereit)', type: 'positive', weight: 3 },
  six_insider: { label: 'SIX Insider (CH)', glossar: 'SIX Insider (CH)', short: 'CH', icon: Flag, description: 'SIX SER: Management-Transaktion eines Schweizer Emittenten (Pflichtmeldung)', type: 'positive', weight: 3 },
  form4_cluster: { label: 'Form 4 Cluster (Probe)', glossar: 'Form 4 Cluster', short: 'F4', icon: Users, description: 'SEC Form 4 Insider-Cluster (Probe — Kill-Gate 2026-08-15)', type: 'positive', weight: 2 },
  estimate_revision: { label: 'Estimate-Revision (Probe)', glossar: 'Estimate-Revision', short: 'ER', icon: BarChart3, description: 'FMP Analyst-Estimates Aufwärts-Revision (Probe — Kill-Gate 2026-08-15)', type: 'positive', weight: 1 },
}

export const MOMENTUM_CONFIG = {
  tailwind: {
    short: 'T',
    label: 'Branchen-Tailwind',
    color: 'bg-success/15 text-success',
    description: 'Branche mit positivem Momentum (perf_1m und perf_3m positiv) und überdurchschnittlichem Volumen-Inflow (RVOL > 1.2). +1 Score-Bonus.',
  },
  headwind: {
    short: 'H',
    label: 'Branchen-Headwind',
    color: 'bg-danger/15 text-danger',
    description: 'Branche mit negativem 1M-Momentum und unterdurchschnittlichem Volumen. Klassifikation persistiert; aktuell kein Score-Effekt.',
  },
  concentrated: {
    short: 'K',
    label: 'Branche konzentriert',
    color: 'bg-warning/15 text-warning',
    description: 'Branche durch eine einzelne Aktie dominiert (Top1 > 50% MCap oder effektive Mitgliederzahl < 5). Kein Branchen-Bonus, da Performance kein echtes Sektorsignal wäre.',
  },
}

export const MOMENTUM_FILTER_VALUES = ['tailwind', 'neutral', 'headwind', 'concentrated']
