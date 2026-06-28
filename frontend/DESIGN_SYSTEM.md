# OpenFolio Design-System (Redesign 2026)

Verbindliches UI-System für das Frontend. **Jede neue oder geänderte UI nutzt dieses System** — keine Alt-Palette, keine Ad-hoc-Farben, keine eigenen Karten/Buttons wo Primitives existieren. Referenz-Seiten (Gold-Standard): `src/pages/Transactions.jsx`, `src/pages/Portfolio.jsx`.

Korrektheits-Invarianten bleiben unberührt: Formatter (`formatCHF`/`formatPct`/`pnlColor` aus `src/lib/format.js`) wiederverwenden — Styling ändert **nie** eine Zahlen-Definition.

## Schrift
- Body: `font-sans` = IBM Plex Sans · Zahlen/Labels/Ticker/Codes: `font-mono` = IBM Plex Mono
- Global: `tabular-nums`, antialiased. Self-hosted via `@fontsource` (Import in `src/index.jsx`) — **kein** Google-Fonts-CDN (Privacy).

## Farb-Tokens (Tailwind — IMMER nutzen, nie Hex hartkodieren)
Flächen: `bg-body` (#0a0d12) · `bg-sidebar` (#0c0f15) · `bg-card` (#11151d) · `bg-card-2` (nested #0f141c) · `bg-surface` (Buttons/Inputs #10151d) · `bg-table-head` (#0e131b) · `bg-hover` (Row-Hover #141a23) · `bg-modal` (#121821) · `bg-active-tint` (#15203a)
Rahmen: `border-border` (Karte #222a36) · `border-border-soft` (Header #1a212c) · `border-border-2` (innen #1c2331) · `border-border-row` (Zeilen #161d27) · `border-border-chip` · `border-border-hover` · `border-border-active`
Text: `text-text-primary` (#e9eef5) · `text-text-secondary` (muted #9aa6b6) · `text-text-muted` (dim #7a8698) · `text-text-bright` (#cbd4e0) · `text-text-label` (Mono-Mikro #626d7d) · `text-text-faint` (#5f6d7d) · `text-link` (#9bb4e8)
Akzent/Semantik: `primary` (#5b8def) · `success` (#45c08a) · `danger` (#e8625a) · `warning` (#e0a64b) · `etf` (#29c3b1)
Anlageklassen-Akzente (für Dots/Badges): Aktien #5b8def, ETF #29c3b1, Krypto #b06ee8, Edelmetall #e0a64b, Immobilien #6b8aa0, PE #8a7de0, Cash #7a8698, Vorsorge #45c08a
Radius: Karten `rounded-card` (11px), Buttons/Inputs/Chips `rounded-lg` (8px), Modal `rounded-[14px]`.

## Shared-Primitives (`src/components/ui/`)
- `PageHeader` — sticky Topbar `<PageHeader title subtitle actions showSearch showBell alertCount onBellClick />` (bricht aus dem Layout-Padding aus; Layout nicht anfassen)
- `Card` (+ `CardLabel`, `CardTitle`) — Standard-Karte
- `StatTile` — `<StatTile label value sub tone mono />` (tone: success|danger|warning|primary|bright|default)
- `FilterChips` — `<FilterChips options={[{key,label,count?}]} value onChange />`
- `Badge`, `TypeBadge` — `<TypeBadge label kind="class|txn" />`
- `TickerChip` — Mono-Ticker-Chip
- `Button` — `<Button variant="primary|secondary|ghost" icon={Icon}>…</Button>`

## Layout-Muster pro Seite
```jsx
return (
  <div className="pb-10">
    <PageHeader title="…" subtitle="…" actions={<>…</>} />
    <div className="flex flex-col gap-[18px]">… Inhalt …</div>
  </div>
)
```
Loading/Error: denselben `PageHeader` rendern + `Skeleton` bzw. Fehler-Box (`rounded-card border border-danger/30 bg-danger/10`).

## Bausteine
- Karte: `bg-card border border-border rounded-card overflow-hidden`
- Sektions-Header in Karte: `px-[18px] py-4 border-b border-border-2 flex items-center justify-between`, Titel `text-sm font-semibold`, optional Dot (`w-[9px] h-[9px] rounded-[3px]` in Klassenfarbe)
- Tabelle: thead-Row `bg-table-head border-b border-border-2 font-mono text-[10px] uppercase tracking-[0.05em] text-text-faint`; tbody-Row `border-b border-border-row hover:bg-hover`; Zahlen-Zellen `font-mono tabular-nums`
- Modal: Overlay `fixed inset-0 z-[80] bg-[#04070c]/[0.72] backdrop-blur-sm flex items-center justify-center`; Dialog `bg-modal border border-border-hover rounded-[14px] shadow-2xl`; `useFocusTrap`/`useScrollLock`/`useEscClose` behalten.
- Heatmap-Zelle: grün `rgba(69,192,138,a)` / rot `rgba(232,98,90,a)`, `a` nach Betrag skaliert.

## Regeln für neue/geänderte UI (Audit-relevant)
1. **Tokens statt Hex.** Keine `bg-[#…]`, keine Alt-Palette (`#070a10`, `#0f1520`, `#3b82f6`, `#1c2638`), kein `border-white/[…]`.
2. **Primitives nutzen** statt eigener Karten/Buttons/Badges.
3. **Seiten haben einen `PageHeader`** (sticky Shell), nicht eigene Ad-hoc-Header.
4. **IBM Plex** für Zahlen/Labels (`font-mono` + `tabular-nums`).
5. **Responsive.** Desktop = Sidebar; Mobil (`<md`) = Bottom-Tab-Nav (`components/MobileNav.jsx`) + `md:hidden`-Mobile-Layouts (dichte Tabellen → Karten/Listen). Desktop-Inhalt in `hidden md:block`/`hidden md:flex` kapseln, Mobile-Block als `md:hidden`; gemeinsamer `PageHeader` dient als Top-App-Bar. Sekundär-Bereiche laufen mobil über die „Mehr"-Seite (`/mehr`). Light-Mode bewusst geparkt. Deutsch (Schweiz, **kein ß → ss**), echte Umlaute. Neutrale Signal-Sprache.
6. Datenanbindung/Berechnungen unverändert; Formatter wiederverwenden.
