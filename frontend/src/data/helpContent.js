// Help content for OpenFolio — all text in German.
// The articles are Markdown files under src/content/help/<section>/<id>.md
// (format: see lib/helpMarkdown.js); the sections are listed in
// content/help/sections.json. This module only loads both at build time.

import { buildHelpSections } from '../lib/helpMarkdown'
import sections from '../content/help/sections.json'

/** Sections in display order (content/help/sections.json). The folder name is the section id. */
export const HELP_SECTION_META = sections

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
