from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.audit_log import AuditLogRead

router = APIRouter()


@router.get("/audit", response_model=list[AuditLogRead])
def list_audit_logs(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[AuditLog]:
    return db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(100).all()
