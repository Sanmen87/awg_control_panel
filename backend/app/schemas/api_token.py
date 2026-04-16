from datetime import datetime

from pydantic import BaseModel, Field


class ApiTokenCreate(BaseModel):
    name: str
    scopes: list[str] = Field(default_factory=list)


class ApiTokenRead(BaseModel):
    id: int
    name: str
    token_prefix: str
    scopes: list[str] = Field(default_factory=list)
    is_active: bool
    last_used_at: datetime | None = None
    last_used_ip: str | None = None
    created_at: datetime
    updated_at: datetime


class ApiTokenCreated(ApiTokenRead):
    token: str
