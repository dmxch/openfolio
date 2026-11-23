// Help content for OpenFolio — all text in German.
// The articles are Markdown files under src/content/help/<section>/<id>.md
// (format: see lib/helpMarkdown.js). This module only defines the sections
// and loads the files at build time.

import { buildHelpSections } from '../lib/helpMarkdown'

/** Sections in display order. The folder name under content/help/ is the section id. */
export const HELP_SECTION_META = [
  { id: 'erste-schritte', title: 'Erste Schritte', icon: 'Rocket' },
  { id: 'portfolio-management', title: 'Portfolio-Management', icon: 'Briefcase' },
  { id: 'scoring-system', title: 'Scoring-System', icon: 'Target' },
  { id: 'marktanalyse', title: 'Marktanalyse', icon: 'BarChart3' },
  { id: 'aktien-analyse', title: 'Aktien-Analyse', icon: 'TrendingUp' },
  { id: 'risikomanagement', title: 'Risikomanagement', icon: 'Shield' },
  { id: 'watchlist', title: 'Watchlist', icon: 'Eye' },
  { id: 'glossar', title: 'Glossar', icon: 'BookOpen' },
]

export const HELP_CATEGORIES = Object.fromEntries(HELP_SECTION_META.map((s) => [s.id, s.title]))

const files = import.meta.glob('../content/help/**/*.md', {
  query: '?raw',
  import: 'default',
  eager: true,
})

export const HELP_SECTIONS = buildHelpSections(HELP_SECTION_META, files)
