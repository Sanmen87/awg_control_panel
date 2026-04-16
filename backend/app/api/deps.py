from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import ALGORITHM
from app.db.session import get_db
from app.models.agent_node import AgentNode
from app.models.api_token import ApiToken
from app.models.user import User
from app.services.app_settings import AppSettingsService
from app.services.api_tokens import ApiTokenService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_v1_prefix}/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc

    user = db.query(User).filter(User.username == username, User.is_active.is_(True)).first()
    if user is None:
        raise credentials_exception
    return user


def get_current_agent(
    x_agent_token: str = Header(..., alias="X-Agent-Token"),
    db: Session = Depends(get_db),
) -> AgentNode:
    agent = db.query(AgentNode).filter(AgentNode.token == x_agent_token).first()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent token")
    return agent


def get_current_api_token(
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
    x_api_token: str | None = Header(None, alias="X-API-Token"),
    db: Session = Depends(get_db),
) -> ApiToken:
    raw_token = x_api_token
    if not raw_token and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            raw_token = value.strip()
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API token")
    if not AppSettingsService().get_web_settings(db).external_api_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="External API is disabled")

    client_ip = request.client.host if request.client else None
    token = ApiTokenService().authenticate(db, raw_token, client_ip=client_ip)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")
    return token
