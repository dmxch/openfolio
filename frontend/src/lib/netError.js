/* Netzwerkfehler in verstaendliche deutsche Meldungen uebersetzen.
 *
 * Hintergrund: `fetch` lehnt bei Verbindungsproblemen mit einem nackten
 * TypeError ab — "Failed to fetch" (Chrome), "NetworkError when attempting
 * to fetch resource" (Firefox), "Load failed" (Safari). Diese Texte sind
 * englisch, browserabhaengig und fuer Nutzer bedeutungslos.
 *
 * Verschaerfend: der Service Worker liefert die App-Shell auch ohne Netz aus
 * (public/sw.js, Navigation -> Cache-Fallback). Die Seite rendert also
 * vollstaendig, obwohl keine einzige API-Anfrage durchkommt — die
 * Fehlermeldung ist der EINZIGE Hinweis auf die fehlende Verbindung und
 * muss deshalb selbst erklaeren, was los ist.
 *
 * Wichtig: "keine Antwort" (Netzfehler) und "Server hat Nein gesagt"
 * (HTTP-Status) sind verschiedene Dinge. Nur Ersteres landet hier — an
 * Abbruechen (AbortError) wird bewusst nichts veraendert.
 */

export const OFFLINE_MESSAGE =
  'Keine Internetverbindung. Prüfe deine Verbindung und versuche es erneut.'

export const UNREACHABLE_MESSAGE =
  'Server nicht erreichbar. Bitte versuche es in einem Moment erneut.'

/** true, wenn der Fehler ein abgebrochener Request ist (kein echter Fehler). */
export function isAbortError(err) {
  return err?.name === 'AbortError'
}

/** true, wenn der Fehler von toNetworkError() stammt. */
export function isNetworkError(err) {
  return err?.isNetworkError === true
}

/**
 * Verpackt einen fetch-Rejection in einen Error mit deutscher Meldung.
 * Der Originalfehler bleibt als `cause` erhalten (Debugging), das Flag
 * `isNetworkError` erlaubt Aufrufern, Netzfehler von Auth-Fehlern zu
 * unterscheiden.
 */
export function toNetworkError(err) {
  // navigator.onLine ist nur bei `false` aussagekraeftig: true bedeutet
  // lediglich "Interface hat eine Route", nicht "Internet erreichbar".
  const offline = typeof navigator !== 'undefined' && navigator.onLine === false
  const wrapped = new Error(offline ? OFFLINE_MESSAGE : UNREACHABLE_MESSAGE, { cause: err })
  wrapped.isNetworkError = true
  return wrapped
}

/**
 * fetch mit uebersetzten Netzwerkfehlern. Antworten werden unveraendert
 * durchgereicht — auch 4xx/5xx: die gehoeren dem Aufrufer, nicht hierher.
 */
export async function netFetch(url, options) {
  try {
    return await fetch(url, options)
  } catch (err) {
    if (isAbortError(err)) throw err
    throw toNetworkError(err)
  }
}
