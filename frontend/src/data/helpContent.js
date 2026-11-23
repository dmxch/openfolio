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

// An empty glob means the Markdown files did not reach the build (e.g. excluded
// from the Docker context). Vite does not run this module at build time, so the
// error surfaces in the test suite and when the help page loads, not in the build.
if (Object.keys(files).length === 0) {
  throw new Error('helpContent: no help articles found under src/content/help/')
}

export const HELP_SECTIONS = buildHelpSections(HELP_SECTION_META, files)
