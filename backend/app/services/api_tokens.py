from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import api_token_prefix, generate_api_token, hash_api_token
from app.models.api_token import ApiToken


ALLOWED_API_TOKEN_SCOPES = {
    "servers:read",
    "clients:read",
    "clients:write",
    "materials:read",
}


class ApiTokenService:
    WEB_EXTERNAL_TOKEN_NAME = "web-external-api"

    def create_token(self, db: Session, *, name: str, scopes: list[str]) -> tuple[ApiToken, str]:
        clean_name = name.strip()
        if not clean_name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token name is required")
        clean_scopes = self.validate_scopes(scopes)
        prefix, raw_token = generate_api_token()
        token = ApiToken(
            name=clean_name,
            token_hash=hash_api_token(raw_token),
            token_prefix=prefix,
            scopes_json=json.dumps(clean_scopes),
            is_active=True,
        )
        db.add(token)
        db.commit()
        db.refresh(token)
        return token, raw_token

    def rotate_named_token(self, db: Session, *, name: str, scopes: list[str]) -> tuple[ApiToken, str]:
        clean_name = name.strip()
        if not clean_name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token name is required")
        clean_scopes = self.validate_scopes(scopes)
        prefix, raw_token = generate_api_token()
        token = db.query(ApiToken).filter(ApiToken.name == clean_name).first()
        if token is None:
            token = ApiToken(name=clean_name, token_hash="", token_prefix="", scopes_json="[]", is_active=True)
        token.token_hash = hash_api_token(raw_token)
        token.token_prefix = prefix
        token.scopes_json = json.dumps(clean_scopes)
        token.is_active = True
        token.last_used_at = None
        token.last_used_ip = None
        db.add(token)
        db.commit()
        db.refresh(token)
        return token, raw_token

    def get_web_external_token(self, db: Session) -> ApiToken | None:
        return db.query(ApiToken).filter(ApiToken.name == self.WEB_EXTERNAL_TOKEN_NAME, ApiToken.is_active.is_(True)).first()

    def authenticate(self, db: Session, raw_token: str, *, client_ip: str | None = None) -> ApiToken | None:
        prefix = api_token_prefix(raw_token)
        if not prefix:
            return None
        token_hash = hash_api_token(raw_token)
        token = (
            db.query(ApiToken)
            .filter(
                ApiToken.token_prefix == prefix,
                ApiToken.token_hash == token_hash,
                ApiToken.is_active.is_(True),
            )
            .first()
        )
        if token:
            token.last_used_at = datetime.now(UTC)
            token.last_used_ip = client_ip
            db.add(token)
            db.commit()
            db.refresh(token)
        return token

    def scopes_for(self, token: ApiToken) -> list[str]:
        try:
            values = json.loads(token.scopes_json or "[]")
        except json.JSONDecodeError:
            return []
        if not isinstance(values, list):
            return []
        return [str(value) for value in values]

    def validate_scopes(self, scopes: list[str]) -> list[str]:
        clean_scopes = sorted({scope.strip() for scope in scopes if scope.strip()})
        invalid = [scope for scope in clean_scopes if scope not in ALLOWED_API_TOKEN_SCOPES]
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported API token scopes: {', '.join(invalid)}",
            )
        return clean_scopes

    def require_scope(self, token: ApiToken, scope: str) -> None:
        scopes = self.scopes_for(token)
        if scope not in scopes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing API token scope: {scope}")
