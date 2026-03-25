from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


class AuditService:
    def log(
        self,
        db: Session,
        *,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        details: str | None = None,
        user_id: int | None = None,
    ) -> AuditLog:
        record = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

