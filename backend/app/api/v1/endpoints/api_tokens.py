import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.api_token import ApiToken
from app.models.user import User
from app.schemas.api_token import ApiTokenCreate, ApiTokenCreated, ApiTokenRead
from app.services.api_tokens import ApiTokenService
from app.services.audit import AuditService

router = APIRouter()


def _read_token(token: ApiToken, raw_token: str | None = None) -> ApiTokenRead | ApiTokenCreated:
    scopes = ApiTokenService().scopes_for(token)
    payload = {
        "id": token.id,
        "name": token.name,
        "token_prefix": token.token_prefix,
        "scopes": scopes,
        "is_active": token.is_active,
        "last_used_at": token.last_used_at,
        "last_used_ip": token.last_used_ip,
        "created_at": token.created_at,
        "updated_at": token.updated_at,
    }
    if raw_token is not None:
        return ApiTokenCreated(**payload, token=raw_token)
    return ApiTokenRead(**payload)


@router.get("", response_model=list[ApiTokenRead])
def list_api_tokens(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[ApiTokenRead]:
    tokens = db.query(ApiToken).order_by(ApiToken.created_at.desc()).all()
    return [_read_token(token) for token in tokens]  # type: ignore[list-item]


@router.post("", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED)
def create_api_token(
    payload: ApiTokenCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiTokenCreated:
    try:
        token, raw_token = ApiTokenService().create_token(db, name=payload.name, scopes=payload.scopes)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="API token name already exists") from exc
    AuditService().log_user(
        db,
        current_user,
        action="api_token.created",
        resource_type="api_token",
        resource_id=str(token.id),
        details=f"API token {token.name} created",
        metadata_json=json.dumps({"scopes": ApiTokenService().scopes_for(token)}),
    )
    return _read_token(token, raw_token)  # type: ignore[return-value]


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_token(
    token_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    token = db.query(ApiToken).filter(ApiToken.id == token_id).first()
    if not token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API token not found")
    token.is_active = False
    db.add(token)
    db.commit()
    AuditService().log_user(
        db,
        current_user,
        action="api_token.revoked",
        resource_type="api_token",
        resource_id=str(token.id),
        details=f"API token {token.name} revoked",
    )
