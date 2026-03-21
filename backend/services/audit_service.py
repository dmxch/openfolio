import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Request
from models.admin_audit_log import AdminAuditLog
from utils import get_client_ip


async def log_admin_action(
    db: AsyncSession,
    admin_id: uuid.UUID,
    action: str,
    target_user_id: uuid.UUID | None = None,
    details: dict | None = None,
    request: Request | None = None,
):
    entry = AdminAuditLog(
        admin_id=admin_id,
        action=action,
        target_user_id=target_user_id,
        details=json.dumps(details) if details else None,
        ip_address=get_client_ip(request) if request else None,
    )
    db.add(entry)
    await db.flush()
