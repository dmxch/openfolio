import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from models.admin_audit_log import AdminAuditLog


async def log_admin_action(
    db: AsyncSession,
    admin_id: uuid.UUID,
    action: str,
    target_user_id: uuid.UUID | None = None,
    details: dict | None = None,
    client_ip: str | None = None,
):
    entry = AdminAuditLog(
        admin_id=admin_id,
        action=action,
        target_user_id=target_user_id,
        details=json.dumps(details) if details else None,
        ip_address=client_ip,
    )
    db.add(entry)
    await db.flush()
