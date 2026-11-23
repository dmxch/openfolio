// Help articles live as Markdown files under src/content/help/<section>/<id>.md.
// Each file starts with a frontmatter block; values are JSON literals (valid YAML too),
// so external builds can read the same files with a regular YAML parser.
//
//   ---
//   id: "csv-import"
//   title: "CSV-Import"
//   summary: "…"
//   section: "erste-schritte"
//   order: 40
//   ---
//
//   Body text (## Heading, **bold**, > Callout, [text](#id))

const FRONTMATTER = /^---\n([\s\S]*?)\n---\n\n?([\s\S]*)$/
const REQUIRED = ['id', 'title', 'summary', 'section', 'order']

/** Parses one Markdown help file into `{ ...frontmatter, content }`. */
export function parseHelpArticle(raw, source = 'help article') {
  const match = FRONTMATTER.exec(String(raw).replace(/\r\n/g, '\n'))
  if (!match) throw new Error(`${source}: frontmatter block missing`)

  const meta = {}
  for (const line of match[1].split('\n')) {
    if (!line.trim()) continue
    const sep = line.indexOf(': ')
    if (sep < 1) throw new Error(`${source}: invalid frontmatter line "${line}"`)
    const key = line.slice(0, sep).trim()
    const value = line.slice(sep + 2).trim()
    try {
      meta[key] = JSON.parse(value)
    } catch {
      meta[key] = value
    }
  }

  for (const key of REQUIRED) {
    if (meta[key] === undefined || meta[key] === '') {
      throw new Error(`${source}: frontmatter field "${key}" missing`)
    }
  }

  return { ...meta, content: match[2].replace(/\n$/, '') }
}

/**
 * Builds the section list the help page renders.
 * `sectionMeta`: ordered `[{ id, title, icon }]`; `files`: `{ path: rawMarkdown }`.
 */
export function buildHelpSections(sectionMeta, files) {
  const bySection = new Map(sectionMeta.map((s) => [s.id, []]))
  const seen = new Set()

  for (const [path, raw] of Object.entries(files)) {
    const { section, order, ...article } = parseHelpArticle(raw, path)
    if (!bySection.has(section)) throw new Error(`${path}: unknown section "${section}"`)
    if (seen.has(article.id)) throw new Error(`${path}: duplicate article id "${article.id}"`)
    seen.add(article.id)
    bySection.get(section).push({ order, article })
  }

  return sectionMeta.map((s) => ({
    ...s,
    articles: bySection
      .get(s.id)
      .sort((a, b) => a.order - b.order)
      .map((entry) => entry.article),
  }))
}
