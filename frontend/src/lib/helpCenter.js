// Public help center on the project website. Every article of the in-app help
// has a page there: <HELP_CENTER_URL>/<section id>/<article id>.

export const HELP_CENTER_URL = 'https://openfolio.ch/hilfe'

/** URL of an article in the public help center. */
export function helpCenterUrl(sectionId, articleId) {
  return `${HELP_CENTER_URL}/${encodeURIComponent(sectionId)}/${encodeURIComponent(articleId)}`
}
