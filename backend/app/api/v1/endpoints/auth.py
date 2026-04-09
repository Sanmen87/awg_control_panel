from fastapi import APIRouter
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, UserRead
from app.services.audit import AuditService
from app.services.login_guard import LoginGuardService

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenResponse:
    guard = LoginGuardService()
    audit = AuditService()
    client_ip = guard.get_client_ip(request)
    decision = guard.assert_allowed(request, payload.username)
    if not decision.allowed:
        audit.log(
            db,
            action="auth_login_blocked",
            resource_type="security",
            resource_id=payload.username.strip() or None,
            details=f"Blocked login attempt for username='{payload.username.strip()}' from ip='{client_ip}'. Retry after {decision.retry_after_seconds}s.",
        )
        if decision.retry_after_seconds > 0:
            response.headers["Retry-After"] = str(decision.retry_after_seconds)
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=decision.detail)

    user = db.query(User).filter(User.username == payload.username, User.is_active.is_(True)).first()
    if not user or not verify_password(payload.password, user.password_hash):
        failure = guard.register_failure(request, payload.username)
        audit.log(
            db,
            action="auth_login_failed",
            resource_type="security",
            resource_id=payload.username.strip() or None,
            user_id=user.id if user else None,
            details=f"Failed login for username='{payload.username.strip()}' from ip='{client_ip}'.",
        )
        if not failure.allowed and failure.retry_after_seconds > 0:
            audit.log(
                db,
                action="auth_login_banned",
                resource_type="security",
                resource_id=payload.username.strip() or None,
                user_id=user.id if user else None,
                details=f"Temporary login ban triggered for username='{payload.username.strip()}' from ip='{client_ip}' for {failure.retry_after_seconds}s.",
            )
            response.headers["Retry-After"] = str(failure.retry_after_seconds)
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=failure.detail)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    guard.register_success(request, payload.username)
    return TokenResponse(access_token=create_access_token(user.username), token_type="bearer")


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user
