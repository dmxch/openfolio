"""Re-Gate branchen-flow (direction-signed) — läuft via cron am 2026-07-06.

Wiederholung des Phase-0-Kill-Gates vom 2026-05-25. Umbau 2026-07-02
(Alpha-Audit Befund 2 + finance-Memory project_branchen_flow, Korrektur-Block
2026-05-29): Das alte Script testete rvol/turnover VORZEICHEN-BLIND — die
produktive Branchen-Rotations-Methode (Input/branchen_rotation_method.md,
finance-Workspace) liest Flow aber nur MIT positiver Momentum-Richtung.
Ein blindes Verdikt wäre ein Urteil über das falsche (ungetestete) Signal.

Drei direction-signed Test-Arme, jeweils ohne konzentrierte Branchen
(top1_weight > 0.5 oder effective_n < 5 — bestehende Ausschluss-Logik):
  A  rvol-primär     | Gate perf_1m > 0 — Top-rvol-Quartil der Kandidaten mit
                       positivem 1M-Momentum.
  B  turnover-primär | Gate perf_1m > 0 — dito mit turnover_ratio.
  C  Produktiv-Regel momentum_pass UND flow_pass — wie in
     branchen_rotation_method.md: Rang(perf_3m) ≤ 25 UND perf_1m > 0 UND
     Rang(turnover) ≤ 25 UND value_traded > Tages-Median. Ränge über das
     volle Tages-Universum (inkl. konzentrierte), wie in der Produktiv-Methode;
     der Konzentrations-Ausschluss greift nur auf die TOP-Auswahl/Messung.

Messung je Arm: TOP = Arm-Auswahl, REST = restliches nicht-konzentriertes
Universum am selben Tag mit Forward-Wert (nicht nur die gegateten Kandidaten —
alle Arme messen gegen denselben Markt und bleiben vergleichbar).
Forward-Proxy: perf_1w am Snapshot ~T+7 (Fenster T+5..T+10). Median-Forward
TOP vs. REST, gepoolt + pro Tag. Reiner Vorzeichen-Test, nicht signifikant.

Verdikt: auf den forward-stärksten Arm, der die GRÜN-Kriterien erfüllt
(Spread > 0 UND ≥ 55 % Tage positiv, bei ≥ 8 messbaren Tagen). Kein Arm
GRÜN → ROT/RAUSCHIG. Coverage überall zu dünn → AMBER. Die Arm-Ergebnisse
werden einzeln ausgewiesen — der Folge-Schritt (Skill-Bau auf dem stärksten
Arm) braucht sie.

Zum Vergleich laufen die alten vorzeichen-blinden Varianten (exakte
Phase-0-Semantik, unverändert) als Kontext mit. Read-only auf
market_industries. Kein Mail-Versand — Output geht via run.sh in die
result-Datei.

Erster Gate (2026-05-25): turnover-Level ohne Kante (−0.17pp ohne
konzentrierte), rvol nur auf 9 Tagen testbar (+0.40pp, 7/9) — beides blind.
"""
import asyncio
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from db import async_session
from models.market_industry import MarketIndustry

MIN_UNIVERSE = 12          # Mindestgrösse nicht-konzentriertes Universum pro Tag (wie Phase-0)
MIN_GATED_CANDIDATES = 8   # Arme A/B: min. Kandidaten mit perf_1m>0 (Top-Quartil ≥ 2)
MIN_RULE_TOP = 2           # Arm C: min. Branchen, die die Produktiv-Regel bestehen
MIN_DAYS_VERDICT = 8       # min. messbare Tage für ein Verdikt (wie Phase-0)


def median(xs):
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return None
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2


async def main():
    async with async_session() as db:
        rows = (await db.execute(select(
            MarketIndustry.slug, MarketIndustry.scraped_at,
            MarketIndustry.value_traded, MarketIndustry.market_cap,
            MarketIndustry.perf_1m, MarketIndustry.perf_3m,
            MarketIndustry.perf_1w,
            MarketIndustry.rvol_20d, MarketIndustry.top1_weight,
            MarketIndustry.effective_n,
        ))).all()

    by_day = defaultdict(dict)
    perf1w = defaultdict(dict)
    rvol_days = set()
    for slug, ts, vt, mcap, p1m, p3m, p1w, rvol, t1w, effn in rows:
        d = ts.date()
        turnover = (float(vt) / float(mcap)) if (vt is not None and mcap and float(mcap) > 0) else None
        concentrated = ((t1w is not None and float(t1w) > 0.5) or
                        (effn is not None and float(effn) < 5))
        by_day[d][slug] = {
            "turnover": turnover,
            "rvol": float(rvol) if rvol is not None else None,
            "perf_1m": float(p1m) if p1m is not None else None,
            "perf_3m": float(p3m) if p3m is not None else None,
            "value_traded": float(vt) if vt is not None else None,
            "concentrated": concentrated,
        }
        if rvol is not None:
            rvol_days.add(d)
        if p1w is not None:
            perf1w[slug][d] = float(p1w)

    dates = sorted(by_day.keys())

    def nearest_forward(d):
        target = d + timedelta(days=7)
        cands = [x for x in dates if d + timedelta(days=5) <= x <= d + timedelta(days=10)]
        return min(cands, key=lambda x: abs((x - target).days)) if cands else None

    # ---------- Vorzeichen-blinde Messung (exakte Phase-0-Semantik, Kontext) ----------
    def run_blind(key, *, exclude_concentrated=False):
        top_fwd, rest_fwd, per_day_spread = [], [], []
        n_days = 0
        for T in dates:
            fdate = nearest_forward(T)
            if fdate is None:
                continue
            scored = []
            for slug, m in by_day[T].items():
                v = m[key]
                if v is None:
                    continue
                if exclude_concentrated and m["concentrated"]:
                    continue
                fwd = perf1w.get(slug, {}).get(fdate)
                if fwd is None:
                    continue
                scored.append((slug, v, fwd))
            if len(scored) < MIN_UNIVERSE:
                continue
            scored.sort(key=lambda x: x[1], reverse=True)
            q = max(1, len(scored) // 4)
            tf = [f for _, _, f in scored[:q]]
            rf = [f for _, _, f in scored[q:]]
            top_fwd += tf
            rest_fwd += rf
            mt, mr = median(tf), median(rf)
            if mt is not None and mr is not None:
                per_day_spread.append(mt - mr)
            n_days += 1
        mt, mr = median(top_fwd), median(rest_fwd)
        return {
            "n_days": n_days, "n_top": len(top_fwd), "n_rest": len(rest_fwd),
            "avg_top": (len(top_fwd) / n_days) if n_days else None,
            "mt": mt, "mr": mr, "spread": (mt - mr) if (mt is not None and mr is not None) else None,
            "pd": len(per_day_spread), "pos": sum(1 for s in per_day_spread if s > 0),
        }

    # ---------- Direction-signed Arme ----------
    def universe(T, fdate):
        """Nicht-konzentrierte Branchen mit Forward-Wert am fdate."""
        out = {}
        for slug, m in by_day[T].items():
            if m["concentrated"]:
                continue
            fwd = perf1w.get(slug, {}).get(fdate)
            if fwd is None:
                continue
            out[slug] = (m, fwd)
        return out

    def top_gated_quartile(key):
        """Arm A/B: Top-Quartil nach `key` unter den Branchen mit perf_1m > 0."""
        def select_top(T, uni):
            cands = [(slug, m[key]) for slug, (m, _) in uni.items()
                     if m[key] is not None and m["perf_1m"] is not None and m["perf_1m"] > 0]
            if len(cands) < MIN_GATED_CANDIDATES:
                return None
            cands.sort(key=lambda x: x[1], reverse=True)
            q = max(1, len(cands) // 4)
            return {slug for slug, _ in cands[:q]}
        return select_top

    def rank_by(day_map, key):
        xs = [(slug, m[key]) for slug, m in day_map.items() if m[key] is not None]
        xs.sort(key=lambda x: x[1], reverse=True)
        return {slug: i + 1 for i, (slug, _) in enumerate(xs)}

    def top_produktiv_regel(T, uni):
        """Arm C: momentum_pass UND flow_pass (branchen_rotation_method.md)."""
        full = by_day[T]  # Ränge/Median über volles Tages-Universum, wie produktiv
        r3m = rank_by(full, "perf_3m")
        rto = rank_by(full, "turnover")
        vts = [m["value_traded"] for m in full.values() if m["value_traded"]]
        vt_med = median(vts)
        if vt_med is None:
            return None
        top = set()
        for slug, (m, _) in uni.items():
            momentum_pass = (r3m.get(slug, 999) <= 25 and
                             m["perf_1m"] is not None and m["perf_1m"] > 0)
            flow_pass = (rto.get(slug, 999) <= 25 and
                         m["value_traded"] is not None and m["value_traded"] > vt_med)
            if momentum_pass and flow_pass:
                top.add(slug)
        return top if len(top) >= MIN_RULE_TOP else None

    def run_signed(select_top):
        top_fwd, rest_fwd, per_day_spread, top_sizes = [], [], [], []
        n_days = 0
        for T in dates:
            fdate = nearest_forward(T)
            if fdate is None:
                continue
            uni = universe(T, fdate)
            if len(uni) < MIN_UNIVERSE:
                continue
            top = select_top(T, uni)
            if not top:
                continue
            tf = [fwd for slug, (_, fwd) in uni.items() if slug in top]
            rf = [fwd for slug, (_, fwd) in uni.items() if slug not in top]
            if not tf or not rf:
                continue
            top_fwd += tf
            rest_fwd += rf
            top_sizes.append(len(tf))
            mt, mr = median(tf), median(rf)
            if mt is not None and mr is not None:
                per_day_spread.append(mt - mr)
            n_days += 1
        mt, mr = median(top_fwd), median(rest_fwd)
        return {
            "n_days": n_days, "n_top": len(top_fwd), "n_rest": len(rest_fwd),
            "avg_top": (sum(top_sizes) / len(top_sizes)) if top_sizes else None,
            "mt": mt, "mr": mr, "spread": (mt - mr) if (mt is not None and mr is not None) else None,
            "pd": len(per_day_spread), "pos": sum(1 for s in per_day_spread if s > 0),
        }

    def print_block(label, r):
        print(f"=== {label} ===")
        if r["mt"] is None:
            print("  zu wenig Daten\n")
            return
        avg = f"{r['avg_top']:.1f}" if r["avg_top"] is not None else "n/a"
        print(f"  gültige Tage: {r['n_days']}  | Obs top/rest: {r['n_top']}/{r['n_rest']}  | Ø TOP-Grösse/Tag: {avg}")
        print(f"  Median Fwd-1w  TOP/REST: {r['mt']:+.2f}% / {r['mr']:+.2f}%")
        print(f"  Spread (TOP-REST)      : {r['spread']:+.2f} pp")
        print(f"  Tage TOP schlägt REST  : {r['pos']}/{r['pd']}\n")

    print(f"Snapshot-Tage gesamt : {len(dates)}  ({dates[0]} .. {dates[-1]})")
    print(f"Tage mit rvol-Wert   : {len(rvol_days)}")
    print("Forward-Proxy        : perf_1w am nächsten Snapshot zu T+7 (Fenster T+5..T+10)")
    print("Messung je Arm       : TOP = Arm-Auswahl, REST = restliches nicht-konzentriertes")
    print("                       Universum desselben Tags (alle Arme gegen denselben Markt)\n")

    arms = [
        ("A", "rvol-primär | perf_1m>0 (ohne konzentrierte)", top_gated_quartile("rvol")),
        ("B", "turnover-primär | perf_1m>0 (ohne konzentrierte)", top_gated_quartile("turnover")),
        ("C", "Produktiv-Regel momentum_pass UND flow_pass (ohne konzentrierte)", top_produktiv_regel),
    ]
    arm_res = {}
    print("== Direction-signed Arme (verdikt-relevant) ==\n")
    for arm_id, label, sel in arms:
        r = run_signed(sel)
        arm_res[arm_id] = (label, r)
        print_block(f"Arm {arm_id}: {label}", r)

    print("== Kontext: vorzeichen-blinde Varianten (Phase-0-Semantik, NICHT verdikt-relevant) ==\n")
    blind_variants = [
        ("rvol (blind, ohne konzentrierte)", "rvol", True),
        ("turnover (blind, ohne konzentrierte)", "turnover", True),
        ("Momentum perf_1m (blind, Vergleich)", "perf_1m", False),
    ]
    for label, key, exc in blind_variants:
        print_block(label, run_blind(key, exclude_concentrated=exc))

    # ---------- Verdikt: forward-stärkster direction-signed Arm ----------
    eligible = {aid: (label, r) for aid, (label, r) in arm_res.items()
                if r["spread"] is not None and r["pd"] >= MIN_DAYS_VERDICT}
    green = {aid: lr for aid, lr in eligible.items()
             if lr[1]["spread"] > 0 and lr[1]["pos"] / lr[1]["pd"] >= 0.55}

    print("------ VERDIKT (direction-signed, forward-stärkster Arm) ------")
    summary = " | ".join(
        f"{aid}: Spread {r['spread']:+.2f}pp, {r['pos']}/{r['pd']} Tage pos."
        if r["spread"] is not None else f"{aid}: zu wenig Daten"
        for aid, (_, r) in sorted(arm_res.items())
    )
    print(f"Arm-Übersicht: {summary}")
    if not eligible:
        print(f"AMBER: kein Arm mit ≥{MIN_DAYS_VERDICT} messbaren Tagen — Coverage zu dünn für ein Urteil.")
        print("-> Später erneut laufen lassen. Mit Harry reden.")
    elif green:
        aid, (label, r) = max(green.items(), key=lambda kv: kv[1][1]["spread"])
        print(f"GRÜN: Arm {aid} ({label}) ist der forward-stärkste Arm, der die Kriterien erfüllt")
        print(f"  (Spread {r['spread']:+.2f}pp > 0, {r['pos']}/{r['pd']} = {r['pos']/r['pd']:.0%} Tage positiv ≥ 55%).")
        print(f"-> /branchen-flow mit Arm {aid} als Primär-Ranking bauen (finance-Workspace),")
        print("   Build-Spec im Plan-File entsprechend anpassen. Bleibt Vorzeichen-Test, nicht signifikant.")
    else:
        aid, (label, r) = max(eligible.items(), key=lambda kv: kv[1][1]["spread"])
        print("ROT/RAUSCHIG: kein Arm erfüllt GRÜN (Spread > 0 UND ≥ 55% Tage positiv).")
        print(f"  Bester Arm {aid} ({label}): Spread {r['spread']:+.2f}pp, {r['pos']}/{r['pd']} Tage positiv.")
        print("-> NICHT bauen. Mit Harry reden, Flow-Definition überdenken.")
    print("Kontext/Methode: openfolio-Memory project_branchen_flow_killgate.md +")
    print("finance-Memory project_branchen_flow.md (Korrektur-Block 2026-05-29).")


asyncio.run(main())
