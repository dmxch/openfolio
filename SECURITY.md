# Sicherheit

## Eine Lücke melden

Bitte **nicht** als öffentliches GitHub-Issue — sonst ist die Lücke bekannt, bevor es einen Fix gibt.

Zwei private Wege:

1. **GitHub Security Advisory** (bevorzugt): Reiter *Security* → *Report a vulnerability*.
2. **E-Mail** an <openfolio@proton.me>, Betreff mit `SECURITY` beginnen.

Hilfreich im Report:

- betroffene Version oder Commit (`/api/health` mit gültigem Token nennt die laufende Version)
- Reproduktionsschritte oder ein minimaler PoC
- erwartetes vs. tatsächliches Verhalten
- deine Einschätzung der Auswirkung (wer kommt an was?)

## Was du erwarten kannst

OpenFolio ist ein Open-Source-Projekt ohne Security-Team und ohne Bug-Bounty. Die folgenden Fristen
sind ernst gemeinte Ziele, keine vertraglichen Zusagen:

| | |
| --- | --- |
| Erste Rückmeldung | innert 7 Tagen |
| Einschätzung (bestätigt / abgelehnt / Duplikat) | innert 14 Tagen |
| Fix bei kritischen Lücken | so schnell wie möglich, Richtwert 30 Tage |
| Offenlegung | nach dem Fix, per Security Advisory + CHANGELOG |

Credit gerne — schreib dazu, unter welchem Namen du genannt werden möchtest (oder dass du es nicht willst).

## Unterstützte Versionen

Sicherheitsfixes gibt es ausschliesslich für die neueste Version auf `main`. Es gibt keine Backports
auf ältere Minor-Versionen — wer selbst hostet, sollte dem aktuellen Tag folgen.

## Scope

**In Scope**

- dieses Repository (Backend, Worker, Frontend, Docker-Setup)
- eine selbst gehostete Instanz in Standard-Konfiguration
- die öffentliche Instanz `cloud.openfolio.ch` inklusive der externen API unter `/api/v1/external`

**Out of Scope**

- Schwachstellen in Drittanbieter-Diensten (yfinance, TradingView, CoinGecko, FRED, FMP, SEC EDGAR …)
- fehlende Härtung ohne belegbaren Angriffspfad (reine Scanner-Ausgaben zu Headern, TLS-Ciphers, …)
- Denial of Service durch reine Lastgenerierung
- Social Engineering, physischer Zugriff, kompromittierte Endgeräte
- Self-XSS und Befunde, die bereits vollen Zugriff auf das Opfer-Konto voraussetzen

**Regeln fürs Testen:** Teste bitte gegen eine eigene Instanz. Auf `cloud.openfolio.ch` sind keine
automatisierten Scanner, kein Bruteforce, keine Lasttests und keine Zugriffe auf fremde Konten
erwünscht — sanfte manuelle Verifikation eines konkreten Verdachts ist in Ordnung.

## Härtungs-Hinweise für Self-Hoster

- `JWT_SECRET` und `ENCRYPTION_KEY` **müssen** eigene, zufällige Werte sein — das Backend verweigert
  den Start mit Platzhaltern (`backend/config.py`).
- Die App nie ohne TLS exponieren; die Security-Header inklusive CSP kommen aus `frontend/nginx.conf`.
  Wer einen eigenen Reverse Proxy davorsetzt, sollte dieselben Header dort **nicht** ein zweites Mal
  setzen (widersprüchliche Werte sind schwer zu debuggen).
- MFA-Pflicht lässt sich in den Admin-Einstellungen erzwingen (aus / nur Admins / ausgewählte / alle).
- Datenbank-Backups verschlüsselt ablegen: sie enthalten Depotdaten, API-Token und Passwort-Hashes.
- Die Registrierung steht per Default auf `invite_only` — offen lassen nur, wenn das bewusst gewollt ist.
- Push-Ziele (ntfy) auf interne Adressen werden geblockt (SSRF-Schutz). Wer einen eigenen ntfy im
  LAN oder den optionalen Container aus `docker-compose.yml` nutzt, gibt den Hostnamen über
  `NTFY_ALLOWED_PRIVATE_HOSTS` frei (kommagetrennt, z. B. `ntfy`).
- SMTP-Server, die Nutzer in ihren Einstellungen eintragen, werden auf internen Adressen ebenfalls
  geblockt (SSRF-Schutz). Ein Mailrelay im eigenen Netz gibt der Betreiber über
  `SMTP_ALLOWED_PRIVATE_HOSTS` frei (kommagetrennt, z. B. `mailrelay.intern`). Die Liste gilt nur
  für SMTP; das globale `SMTP_HOST` braucht keinen Eintrag.
- Der alte Null-Schlüssel (32 Nullen, öffentlich bekannt) entstand in Installationen mit leerem
  `LEGACY_ENCRYPTION_KEY`. Er bleibt per Default aktiv, damit Altwerte lesbar bleiben. Der Dry-Run
  von `backend/scripts/vr11_reencrypt_legacy_fields.py` zählt die betroffenen Werte, `--apply`
  verschlüsselt sie neu. Meldet der Dry-Run danach 0 Werte am Null-Schlüssel:
  `LEGACY_NULL_KEY_ENABLED=false` setzen und Backend und Worker neu starten. Vorher nicht
  abschalten, sonst sind diese Werte nicht mehr lesbar. Aufruf und Ablauf stehen in `.env.example`.
