# Contributing zu OpenFolio

Danke, dass du zu OpenFolio beitragen möchtest! Dieses Dokument erklärt wie.

## Schnellstart

1. Forke das Repository
2. Erstelle einen Feature-Branch: `git checkout -b feat/mein-feature`
3. Mache deine Änderungen
4. Teste: `cd frontend && npm run build` + `cd backend && pytest tests/ -v`
5. Committe mit Conventional Commits: `git commit -m "feat: beschreibung"`
6. Push und erstelle einen Pull Request

## Entwicklungsumgebung

### Voraussetzungen
- Docker & Docker Compose v2
- Git
- Node.js 18+ (für Frontend-Entwicklung)
- Python 3.12+ (für Backend-Entwicklung)

### Setup
```bash
git clone https://github.com/dmxch/openfolio.git
cd openfolio
./init.sh
```

### Lokale Entwicklung
```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

## Regeln

### Sprache
- **Code**: Englisch (Variablen, Funktionen, Kommentare)
- **UI-Texte**: Deutsch
- **Error Messages**: Deutsch (User-facing), Englisch (Logs)
- **Commits**: Englisch

### Commit Messages
Wir nutzen [Conventional Commits](https://www.conventionalcommits.org/):
- `feat:` — Neues Feature
- `fix:` — Bug-Fix
- `refactor:` — Code-Umstrukturierung ohne Funktionsänderung
- `docs:` — Dokumentation
- `chore:` — Build, Dependencies, Konfiguration
- `perf:` — Performance-Optimierung

### Code-Qualität
- **Keine Silent Exceptions**: Jeder `except` Block muss loggen
- **Type Hints**: Alle öffentlichen Funktionen brauchen Typ-Annotationen
- **Pydantic**: Alle API-Inputs über Pydantic Models mit Constraints
- **Tests**: Neue Features sollten Tests mitbringen

### Frontend
- React 18 mit Hooks (keine Class Components)
- Tailwind CSS (Dark Theme)
- Jedes `<input>` braucht ein Label (`htmlFor` + `id`)
- Neue Fachbegriffe mit `<GlossarTooltip>` wrappen und in `glossary.js` eintragen
- Responsive Design: Mindestens Mobile (< 768px) testen
- Lucide Icons (keine anderen Icon-Libraries)

### Backend
- FastAPI mit async/await
- SQLAlchemy 2.0 (async)
- Alle HTTP-Calls über `httpx.AsyncClient`
- Alle SMTP-Calls über `aiosmtplib`
- yfinance NUR über Thread-safe Wrapper (`yf_download()` via `asyncio.to_thread()`)
- Jeder neue Endpoint braucht `Depends(get_current_user)` und `@limiter.limit()`

### Geschützte Dateien
Diese Dateien dürfen **nicht ohne Absprache mit dem Maintainer** geändert werden:
- `backend/services/portfolio_service.py`
- `backend/services/recalculate_service.py`
- `backend/services/price_service.py`
- `backend/utils.py`

Grund: Diese Dateien enthalten die Kern-Performance-Berechnung. Fehler hier können Portfoliowerte verfälschen.

## Was beitragen?

### Gute erste Issues
Wir labeln einsteigerfreundliche Issues mit `good first issue`. Schau dort zuerst.

### Bereiche wo Hilfe willkommen ist
- **Tests**: Die Test-Coverage ist noch niedrig — jeder neue Test hilft
- **Accessibility**: ARIA-Labels, Keyboard-Navigation, Screen-Reader-Support
- **Mobile UX**: Responsive Design für Tabellen und Charts
- **Übersetzungen**: Aktuell nur Deutsch — weitere Sprachen willkommen
- **Dokumentation**: Hilfe-Seite erweitern, Tutorials schreiben
- **Neue Broker-Importe**: CSV-Import-Profile für weitere Broker

### Was wir NICHT annehmen
- Änderungen an der Renditeberechnung ohne vorherige Diskussion
- Neue externe Dependencies ohne Begründung
- Features die den Scope sprengen (z.B. eigenes Trading-System)
- Code ohne Tests für kritische Logik

## Code of Conduct

Sei respektvoll. Wir sind alle hier um zu lernen und ein gutes Tool zu bauen. Konstruktive Kritik willkommen, persönliche Angriffe nicht.

## Fragen?

- **Bugs & Features**: [GitHub Issues](https://github.com/dmxch/openfolio/issues)
- **Fragen & Diskussionen**: [GitHub Discussions](https://github.com/dmxch/openfolio/discussions)
