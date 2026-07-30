/**
 * Klick auf den Overlay-Hintergrund schliesst das Fenster — aber nur, wenn der
 * Klick DORT auch begonnen hat.
 *
 * Vorher hing am Backdrop nur ein onClick. Ein Klick-Event feuert aber auch,
 * wenn Maus-Runter und Maus-Rauf auf verschiedenen Elementen liegen (Ziel ist
 * dann der gemeinsame Vorfahr = der Backdrop). Wer im Formular einen Betrag mit
 * der Maus markierte und dabei über den Fensterrand hinauszog, schloss damit
 * das Fenster und verlor die Eingabe (Feedback 30.7.2026) — dasselbe beim
 * Markieren zum Kopieren.
 *
 * Der Merker liegt in einem WeakSet am DOM-Knoten, nicht im Render-Scope:
 * ``{...backdropClose(onClose)}`` darf so bei jedem Render ein neues Objekt
 * liefern, ohne den Zustand zwischen mousedown und click zu verlieren.
 *
 * Verwendung:
 *   <div className="fixed inset-0 …" {...backdropClose(onClose)}>
 */
const pressedOnBackdrop = new WeakSet()

export default function backdropClose(onClose) {
  return {
    onMouseDown: (e) => {
      if (e.target === e.currentTarget) {
        pressedOnBackdrop.add(e.currentTarget)
      } else {
        pressedOnBackdrop.delete(e.currentTarget)
      }
    },
    onClick: (e) => {
      // Nur der Hintergrund selbst schliesst, nie ein Klick im Inhalt.
      if (e.target !== e.currentTarget) return
      // Maustaste wurde woanders gedrückt (Textauswahl, Drag) — nicht schliessen.
      if (!pressedOnBackdrop.has(e.currentTarget)) return
      pressedOnBackdrop.delete(e.currentTarget)
      onClose?.()
    },
  }
}
