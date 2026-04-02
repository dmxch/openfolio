# OpenFolio Development Team Protocol

> 2-Pizza Team (Amazon-Konzept): Klein, autonom, volle Ownership.
> 10 spezialisierte Agents + 1 Orchestrator. Jeder Agent arbeitet nach international anerkannten Standards.

## Team-Roster

| Agent | Rolle | Model | Kann Code ändern? | Standards |
|-------|-------|-------|-------------------|-----------|
| `@openfolio-pm` | Product Manager | sonnet | Nein | INVEST, IEEE 830, RICE, ISO/IEC 25010 |
| `@openfolio-architect` | Software Architect | opus | Nein | ISO 42010, 12-Factor, SOLID, C4, ADR |
| `@openfolio-ux` | UX Designer | sonnet | Nein | WCAG 2.2 AA, WAI-ARIA 1.2, ISO 9241, Nielsen |
| `@openfolio-security` | Security Engineer | sonnet | Nein | OWASP Top 10/ASVS, CWE-25, STRIDE, ISO 27001, NIST CSF, DSG |
| `@openfolio-perf` | Performance Engineer | sonnet | Nein | RED/USE Method, RAIL, Core Web Vitals, ISO 25023 |
| `@openfolio-qa` | QA Engineer | sonnet | Nein | ISTQB, IEEE 829, ISO 25010, Test Pyramid |
| `@openfolio-devops` | DevOps Engineer | sonnet | Nein (Analyse) | DORA, 12-Factor, CIS Benchmarks, NIST 800-190, SRE |
| `@openfolio-pmm` | Product Marketing | sonnet | Nur Texte | SemVer, Keep a Changelog, ISO 24495-1, FINMA |
| `@openfolio-docs` | Documentation | sonnet | Nur Docs | Diátaxis, IEEE 26515, ISO 24495-1, SemVer |
| `@openfolio-release` | Release Manager | sonnet | Version/Tag | SemVer 2.0, Conventional Commits, DORA |
| `@openfolio-fixer` | **Team Orchestrator** | opus | Ja (Fixes + Features) | Koordiniert alle Agents |

## Shared Context Protocol

### Warum?
Agents müssen wissen was andere Agents entschieden haben. Ohne Shared Context arbeitet jeder Agent blind.

### Mechanismus: `.claude/memory/shared/current-task.md`

**Jeder Agent MUSS bei jedem Aufruf:**
1. `.claude/memory/shared/current-task.md` lesen (falls vorhanden)
2. Seine Sektion aktualisieren bevor er fertig ist
3. Den Handoff-Log ergänzen

**Dateistruktur:**
```markdown
# Current Task — [Feature/Bug Name]

## Status
- Phase: [Planning | Design | Implementation | Review | Done]
- Aktiver Agent: [name]
- Letzter Agent: [name]

## PM — Scope & Requirements
[User Story, Acceptance Criteria]

## ARCH — Technical Design
[API, Models, Services, ADRs]

## UX — Interface Design
[Komponenten, States, A11y]

## SEC — Security Assessment
[Threats, Controls]

## PERF — Performance Considerations
[Caching, Queries, Bottlenecks]

## QA — Test Plan
[Testfälle, Edge Cases]

## DEVOPS — Infrastructure Impact
[Docker, Config, Deployment]

## PMM — Communication
[Feature-Name, UI-Texte, Changelog]

## DOCS — Documentation Impact
[Betroffene Docs, Änderungen]

## Handoff Log
| Zeit | Von | An | Kernaussage |
|------|-----|-----|-------------|
```

### Regeln

1. **Read Before Work** — Immer `current-task.md` lesen bevor man arbeitet
2. **Write Before Done** — Immer eigene Sektion aktualisieren bevor man fertig ist
3. **No Silent Overwrite** — Entscheidungen anderer Agents nicht stillschweigend ändern
4. **Dissent Protocol** — Bei Widerspruch: beide Positionen dokumentieren, PM/Orchestrator entscheidet
5. **Handoff Log** — Jede Übergabe wird protokolliert

## Orchestrierung

### Feature-Entwicklung (Standard-Flow)
```
PM → ARCH → UX → SEC (parallel mit PERF) → [Implementation via Fixer] → QA → DEVOPS → PMM → DOCS
```

### Bugfix
```
QA (Reproduktion) → [Fix via Fixer] → SEC → QA (Verifikation)
```

### Refactoring
```
ARCH → PERF → [Refactor via Fixer] → QA → SEC
```

### Security-Patch
```
SEC → [Fix via Fixer] → QA → DEVOPS
```

### Release
```
Release Manager orchestriert: QA → SEC → ARCH → UX → DOCS → Build → Tag → Push
```

## Konflikt-Eskalation

Bei widersprüchlichen Anforderungen (z.B. SEC will mehr Validierung, PERF will weniger Overhead):
1. Beide Positionen in `current-task.md` dokumentieren
2. Trade-off klar benennen
3. **PM entscheidet** bei Product-Fragen, **ARCH entscheidet** bei technischen Fragen
4. Bei Patt: User fragen

## Projekt-Portabilität

Dieses Team kann in jedes neue Projekt übernommen werden:
1. Agent-Dateien kopieren
2. `TEAM.md` ins Projektroot kopieren
3. `.claude/memory/shared/` Verzeichnis erstellen
4. In `CLAUDE.md` des neuen Projekts referenzieren:
   ```markdown
   ## Development Team
   Siehe `TEAM.md` für Team-Protokoll und Agent-Definitionen.
   ```
5. Projekt-spezifische Regeln in `CLAUDE.md` überschreiben Team-Defaults

## Hierarchie bei Konflikten

1. **CLAUDE.md** (Projekt-Regeln) — höchste Priorität
2. **TEAM.md** (Team-Protokoll) — Arbeitsweise
3. **Agent-Definitionen** (.md Dateien) — Rollen-Details
4. **current-task.md** (Shared Context) — aktuelle Aufgabe
