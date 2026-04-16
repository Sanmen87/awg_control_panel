from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.api_token import ApiToken
from app.models.user import User


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
        actor_type: str | None = None,
        actor_id: str | None = None,
        actor_name: str | None = None,
        metadata_json: str | None = None,
    ) -> AuditLog:
        record = AuditLog(
            user_id=user_id,
            actor_type=actor_type or ("admin_user" if user_id is not None else "system"),
            actor_id=actor_id or (str(user_id) if user_id is not None else None),
            actor_name=actor_name,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            metadata_json=metadata_json,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def log_user(
        self,
        db: Session,
        user: User,
        *,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        details: str | None = None,
        metadata_json: str | None = None,
    ) -> AuditLog:
        return self.log(
            db,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            user_id=user.id,
            actor_type="admin_user",
            actor_id=str(user.id),
            actor_name=user.username,
            metadata_json=metadata_json,
        )

    def log_api_token(
        self,
        db: Session,
        token: ApiToken,
        *,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        details: str | None = None,
        metadata_json: str | None = None,
    ) -> AuditLog:
        return self.log(
            db,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            actor_type="api_token",
            actor_id=str(token.id),
            actor_name=token.name,
            metadata_json=metadata_json,
        )
