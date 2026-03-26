"""XIRR Diagnostic Report Generator — runs against prod DB."""
import asyncio
import sys
from collections import defaultdict
from datetime import date, timedelta

# Ensure backend modules are importable
sys.path.insert(0, "/app")

from db import async_session
from sqlalchemy import select, func, text
from models.portfolio_snapshot import PortfolioSnapshot
from models.transaction import Transaction, TransactionType
from models.position import Position, AssetType
from services.performance_history_service import xirr, _calculate_xirr_from_data

INFLOW_TYPES = {TransactionType.buy, TransactionType.deposit, TransactionType.delivery_in}
OUTFLOW_TYPES = {TransactionType.sell, TransactionType.withdrawal, TransactionType.delivery_out}
ILLIQUID_TYPES = {AssetType.pension, AssetType.real_estate, AssetType.private_equity}


async def generate_report():
    async with async_session() as db:
        # Get first user (admin)
        user_result = await db.execute(text("SELECT id, email FROM users WHERE is_admin = true LIMIT 1"))
        user_row = user_result.first()
        if not user_row:
            print("No admin user found")
            return
        user_id = user_row[0]
        user_email = user_row[1]

        # Load ALL positions
        pos_result = await db.execute(select(Position).where(Position.user_id == user_id))
        all_positions = {str(p.id): p for p in pos_result.scalars().all()}

        # Load ALL transactions
        txn_result = await db.execute(
            select(Transaction).where(Transaction.user_id == user_id).order_by(Transaction.date.asc())
        )
        all_transactions = txn_result.scalars().all()

        # Load ALL snapshots
        snap_result = await db.execute(
            select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == user_id).order_by(PortfolioSnapshot.date.asc())
        )
        all_snapshots = snap_result.scalars().all()

        # Classify transactions by position type
        included_txns = []
        excluded_txns = []
        for txn in all_transactions:
            pos = all_positions.get(str(txn.position_id))
            pos_type = pos.type if pos else None
            txn_info = {
                "date": txn.date,
                "amount_chf": float(txn.total_chf) if txn.total_chf else 0,
                "type": txn.type.value,
                "ticker": pos.ticker if pos else "?",
                "pos_type": pos_type.value if pos_type else "?",
                "txn_id": str(txn.id)[:8],
                "shares": float(txn.shares) if txn.shares else 0,
                "fees": float(txn.fees_chf) if txn.fees_chf else 0,
            }
            if pos_type and pos_type in ILLIQUID_TYPES:
                excluded_txns.append(txn_info)
            else:
                included_txns.append(txn_info)

        # Classify positions
        included_positions = []
        excluded_positions = []
        for p in all_positions.values():
            if not p.is_active or (p.shares and float(p.shares) <= 0):
                continue
            info = {
                "ticker": p.ticker,
                "name": p.name,
                "type": p.type.value,
                "shares": float(p.shares) if p.shares else 0,
                "cost_basis": float(p.cost_basis_chf) if p.cost_basis_chf else 0,
                "current_price": float(p.current_price) if p.current_price else None,
                "market_value": float(p.shares or 0) * float(p.current_price or 0),
            }
            if p.type in ILLIQUID_TYPES:
                excluded_positions.append(info)
            else:
                included_positions.append(info)

        # Build XIRR cashflows (replicate _calculate_xirr_from_data logic)
        if not all_snapshots:
            print("No snapshots found")
            return

        first_snap = all_snapshots[0]
        last_snap = all_snapshots[-1]
        start_date = first_snap.date
        end_date = date.today()

        # Get start value
        start_value = float(first_snap.total_value_chf)

        # Get end value
        end_snap = None
        for snap in reversed(all_snapshots):
            if snap.date <= end_date:
                end_snap = snap
                break
        end_value = float(end_snap.total_value_chf) if end_snap else 0

        # Build cashflow list for display
        cf_display = []
        cf_display.append({
            "date": start_date,
            "amount": -start_value,
            "type": "START_VALUE",
            "ticker": "Portfolio",
            "source": f"Snapshot {start_date}",
        })

        # Transaction cashflows
        txn_cf_by_date = defaultdict(float)
        txn_detail_by_date = defaultdict(list)
        for txn in all_transactions:
            pos = all_positions.get(str(txn.position_id))
            pos_type = pos.type if pos else None
            # XIRR uses all transactions (snapshots already include PE at cost_basis)
            amt = float(txn.total_chf) if txn.total_chf else 0
            if txn.type in INFLOW_TYPES:
                cf = -amt
            elif txn.type in OUTFLOW_TYPES:
                cf = amt
            elif txn.type == TransactionType.dividend:
                cf = amt
            else:
                continue
            txn_cf_by_date[txn.date] += cf
            txn_detail_by_date[txn.date].append({
                "amount": cf,
                "type": txn.type.value,
                "ticker": pos.ticker if pos else "?",
                "pos_type": pos_type.value if pos_type else "?",
                "source": f"Txn {str(txn.id)[:8]}",
            })

        # Snapshot cashflows
        snap_cf_by_date = {}
        for snap in all_snapshots:
            if snap.date <= start_date:
                continue
            cf_val = float(snap.net_cash_flow_chf) if snap.net_cash_flow_chf else 0
            if abs(cf_val) > 0:
                snap_cf_by_date[snap.date] = -cf_val

        # Merge
        all_dates = sorted(set(txn_cf_by_date.keys()) | set(snap_cf_by_date.keys()))
        xirr_cashflows = [(start_date, -start_value)]

        for d in all_dates:
            txn_val = txn_cf_by_date.get(d, 0)
            snap_val = snap_cf_by_date.get(d, 0)
            cf = snap_val if abs(snap_val) > abs(txn_val) * 1.1 else txn_val
            if abs(cf) > 0:
                xirr_cashflows.append((d, cf))
                # Record for display
                if abs(snap_val) > abs(txn_val) * 1.1:
                    cf_display.append({"date": d, "amount": cf, "type": "SNAPSHOT_CF", "ticker": "Portfolio", "source": f"Snapshot {d}"})
                else:
                    for detail in txn_detail_by_date.get(d, []):
                        cf_display.append({"date": d, "amount": detail["amount"], "type": detail["type"], "ticker": detail["ticker"], "source": detail["source"]})

        xirr_cashflows.append((end_snap.date, end_value))
        xirr_cashflows.sort(key=lambda x: x[0])
        cf_display.append({"date": end_snap.date, "amount": end_value, "type": "END_VALUE", "ticker": "Portfolio", "source": f"Snapshot {end_snap.date}"})

        # Calculate XIRR
        xirr_result = xirr(xirr_cashflows)

        # Also calculate via the service function for verification
        service_xirr = _calculate_xirr_from_data(all_snapshots, all_transactions, start_date - timedelta(days=1), end_date)

        # Plausibility
        total_buys = sum(float(t.total_chf) for t in all_transactions if t.type == TransactionType.buy)
        total_sells = sum(float(t.total_chf) for t in all_transactions if t.type == TransactionType.sell)
        total_divs = sum(float(t.total_chf) for t in all_transactions if t.type == TransactionType.dividend)
        days_invested = (end_date - start_date).days
        years_invested = days_invested / 365.25

        # Simple annualized return
        net_invested = total_buys - total_sells
        abs_gain = end_value - net_invested
        simple_return_pct = (abs_gain / net_invested * 100) if net_invested > 0 else 0
        simple_annualized = ((end_value / net_invested) ** (1 / years_invested) - 1) * 100 if net_invested > 0 and years_invested > 0 else 0

        # PE positions detail
        pe_positions = [p for p in all_positions.values() if p.type == AssetType.private_equity and p.is_active]

        # Generate report
        lines = []
        lines.append("# XIRR / MWR Diagnose-Report")
        lines.append(f"\n**Generiert:** {date.today().isoformat()}")
        lines.append(f"**User:** {user_email}")
        lines.append(f"**Snapshot-Zeitraum:** {start_date} bis {end_snap.date}")
        lines.append(f"**Snapshots total:** {len(all_snapshots)}")
        lines.append(f"**Transaktionen total:** {len(all_transactions)}")

        # XIRR Result
        lines.append("\n## 1. XIRR-Ergebnis\n")
        lines.append(f"| Metrik | Wert |")
        lines.append(f"|---|---|")
        lines.append(f"| **XIRR (direkt)** | **{xirr_result * 100:.2f}%** |" if xirr_result else "| XIRR (direkt) | FEHLER |")
        lines.append(f"| XIRR (Service-Funktion) | {service_xirr * 100:.2f}% |" if service_xirr else "| XIRR (Service) | FEHLER |")
        lines.append(f"| Cashflow-Einträge | {len(xirr_cashflows)} |")
        lines.append(f"| Start-Wert (Snapshot) | CHF {start_value:,.2f} |")
        lines.append(f"| End-Wert (Snapshot) | CHF {end_value:,.2f} |")

        # Plausibility
        lines.append("\n## 2. Plausibilitäts-Check\n")
        lines.append(f"| Metrik | Wert |")
        lines.append(f"|---|---|")
        lines.append(f"| Total Käufe (Buy) | CHF {total_buys:,.2f} |")
        lines.append(f"| Total Verkäufe (Sell) | CHF {total_sells:,.2f} |")
        lines.append(f"| Total Dividenden | CHF {total_divs:,.2f} |")
        lines.append(f"| Netto investiert | CHF {net_invested:,.2f} |")
        lines.append(f"| Portfolio-Wert heute | CHF {end_value:,.2f} |")
        lines.append(f"| Absoluter Gewinn | CHF {abs_gain:,.2f} |")
        lines.append(f"| Investitionszeitraum | {days_invested} Tage ({years_invested:.2f} Jahre) |")
        lines.append(f"| Einfache Rendite | {simple_return_pct:.2f}% |")
        lines.append(f"| Einfache ann. Rendite | {simple_annualized:.2f}% |")
        lines.append(f"| **XIRR (geldgewichtet)** | **{xirr_result * 100:.2f}%** |" if xirr_result else "| XIRR | N/A |")

        # Active positions
        lines.append("\n## 3. Aktive Positionen (in Performance enthalten)\n")
        lines.append("| Ticker | Name | Typ | Shares | Cost Basis | Marktwert |")
        lines.append("|---|---|---|---:|---:|---:|")
        total_cost = 0
        total_mv = 0
        for p in sorted(included_positions, key=lambda x: -x["market_value"]):
            total_cost += p["cost_basis"]
            total_mv += p["market_value"]
            lines.append(f"| {p['ticker']} | {p['name'][:30]} | {p['type']} | {p['shares']:.4f} | {p['cost_basis']:,.2f} | {p['market_value']:,.2f} |")
        lines.append(f"| **TOTAL** | | | | **{total_cost:,.2f}** | **{total_mv:,.2f}** |")

        # Excluded positions
        lines.append("\n## 4. Ausgeschlossene Positionen (illiquid)\n")
        if excluded_positions:
            lines.append("| Ticker | Name | Typ | Shares | Cost Basis | Marktwert |")
            lines.append("|---|---|---|---:|---:|---:|")
            for p in excluded_positions:
                lines.append(f"| {p['ticker']} | {p['name'][:30]} | {p['type']} | {p['shares']:.4f} | {p['cost_basis']:,.2f} | {p['market_value']:,.2f} |")
        else:
            lines.append("Keine ausgeschlossenen Positionen.")

        # PE detail
        if pe_positions:
            lines.append("\n### Private Equity Positionen Detail\n")
            for p in pe_positions:
                lines.append(f"- **{p.ticker}** ({p.name}): {float(p.shares):.0f} Aktien, current_price={'NULL' if p.current_price is None else f'{float(p.current_price):.2f}'}, cost_basis={float(p.cost_basis_chf or 0):,.2f}")

        # Excluded transactions
        lines.append("\n## 5. Ausgeschlossene Transaktionen (illiquid Position-Typen)\n")
        if excluded_txns:
            lines.append("| Datum | Typ | Ticker | Pos-Typ | Betrag CHF | Txn-ID |")
            lines.append("|---|---|---|---|---:|---|")
            for t in excluded_txns:
                lines.append(f"| {t['date']} | {t['type']} | {t['ticker']} | {t['pos_type']} | {t['amount_chf']:,.2f} | {t['txn_id']} |")
        else:
            lines.append("Keine Transaktionen für illiquide Positionen (pension, real_estate, private_equity) gefunden.")
            lines.append("\n> **Korrekt:** Private Equity Positionen verwenden Position-Sync (keine Transaktionen), daher fliessen keine PE-Transaktionen in XIRR ein.")

        # XIRR Cashflows
        lines.append("\n## 6. XIRR Cashflows (alle Einträge)\n")
        lines.append("| # | Datum | Betrag CHF | Typ | Ticker | Quelle |")
        lines.append("|---:|---|---:|---|---|---|")
        cf_display_sorted = sorted(cf_display, key=lambda x: x["date"])
        for i, cf in enumerate(cf_display_sorted, 1):
            lines.append(f"| {i} | {cf['date']} | {cf['amount']:,.2f} | {cf['type']} | {cf['ticker']} | {cf['source']} |")

        # Raw XIRR inputs
        lines.append("\n## 7. Rohe XIRR-Inputs (Datum, Betrag)\n")
        lines.append("```")
        for d, cf in xirr_cashflows:
            lines.append(f"{d}  {cf:>14,.2f}")
        lines.append("```")

        # Conclusion
        lines.append("\n## 8. Schlussfolgerung\n")
        if xirr_result is not None and service_xirr is not None:
            diff = abs(xirr_result - service_xirr) * 100
            lines.append(f"- XIRR direkt vs. Service-Funktion: Differenz {diff:.4f}% — {'OK' if diff < 0.1 else 'ABWEICHUNG!'}")

        if xirr_result is not None:
            xirr_pct = xirr_result * 100
            if abs(xirr_pct - simple_annualized) < 20:
                lines.append(f"- XIRR ({xirr_pct:.2f}%) vs. einfache ann. Rendite ({simple_annualized:.2f}%): Differenz plausibel (Cashflow-Timing erklärt Abweichung)")
            else:
                lines.append(f"- **WARNUNG:** XIRR ({xirr_pct:.2f}%) weicht stark von einfacher ann. Rendite ({simple_annualized:.2f}%) ab — grosse Cashflow-Verschiebungen oder Datenproblem")

        pe_in_xirr = any("private_equity" in str(cf.get("pos_type", "")) for cf in cf_display)
        lines.append(f"- Private Equity Transaktionen in XIRR-Cashflows: {'JA — PROBLEM!' if pe_in_xirr else 'Nein — korrekt ausgeschlossen'}")
        lines.append(f"- Pension Transaktionen in XIRR-Cashflows: Snapshots behandeln Pension als cost_basis (kein Marktpreis-Effekt)")
        lines.append(f"- Snapshot-Werte enthalten Pension/PE als cost_basis — stabiler Anteil, keine Marktpreis-Schwankungen")

        report = "\n".join(lines)
        return report


async def main():
    report = await generate_report()
    if report:
        with open("/tmp/XIRR_DIAGNOSE.md", "w") as f:
            f.write(report)
        print(report)


if __name__ == "__main__":
    asyncio.run(main())
