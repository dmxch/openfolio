// Passwortregeln der Oberfläche. Massgebend ist der Server (`validate_password` in
// backend/services/auth_service.py); diese Liste spiegelt seine Regeln zu Länge und
// Zeichenklassen. Wer sie im Backend ändert, zieht sie hier nach. Zwei Regeln prüft
// nur der Server und meldet sie als Fehlertext: höchstens 72 Bytes und die Liste
// häufiger Passwörter.
export const PASSWORD_RULES = [
  { test: (p) => p.length >= 12, label: 'Mindestens 12 Zeichen' },
  { test: (p) => /[A-Z]/.test(p), label: 'Grossbuchstabe' },
  { test: (p) => /[a-z]/.test(p), label: 'Kleinbuchstabe' },
  { test: (p) => /\d/.test(p), label: 'Zahl' },
  { test: (p) => /[!@#$%^&*()_+\-=[\]{}|;:,.<>?]/.test(p), label: 'Sonderzeichen' },
]

export function passwordMeetsRules(password) {
  return PASSWORD_RULES.every((r) => r.test(password))
}

// Backup-Codes lauten XXXXXXXX-XXXXXXXX (16 Hex-Ziffern). Die Eingabe wird in diese
// Form gebracht: Kleinbuchstaben, Leerzeichen oder ein fehlender Bindestrich stören nicht.
export function formatBackupCode(input) {
  const hex = input.toUpperCase().replace(/[^0-9A-F]/g, '').slice(0, 16)
  return hex.length > 8 ? `${hex.slice(0, 8)}-${hex.slice(8)}` : hex
}
