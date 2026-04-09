"""Document screening scans retention by age (365 days, no schema change).

This revision documents the transition from "keep only latest scan"
to "accumulate all scans for 365 days, cleanup via APScheduler job".

No schema changes — retention policy is implemented entirely in Python code:
1. Removed .offset(1) delete logic from api/screening.py:start_scan
2. Removed pre-insert delete from services/screening/screening_service.py:run_scan
3. Added daily cleanup job in backend/worker.py:cleanup_old_screening_scans
   (runs at 04:00 CET, deletes ScreeningScan.started_at < now - 365 days)
4. CASCADE constraint already in place (042_add_fk_screening_results_scan_id.py)

Related: SCOPE_SMART_MONEY_V4.md Block 0a

Revision ID: 048
Revises: 047
Create Date: 2026-04-09
"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "048"
down_revision: Union[str, None] = "047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op: retention policy implemented in Python code, not schema."""
    pass


def downgrade() -> None:
    """No-op: no schema changes to revert."""
    pass
