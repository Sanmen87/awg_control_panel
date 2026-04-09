from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings


@dataclass
class LoginGuardDecision:
    allowed: bool
    retry_after_seconds: int = 0
    detail: str = ""


class LoginGuardService:
    def __init__(self) -> None:
        self._redis: Redis[str] | None = None

    def assert_allowed(self, request: Request, username: str) -> LoginGuardDecision:
        ip_address = self.get_client_ip(request)
        normalized_username = self._normalize_username(username)
        try:
            retry_after_seconds = max(
                self._get_ttl(self._ban_ip_key(ip_address)),
                self._get_ttl(self._ban_user_key(normalized_username)),
            )
        except RedisError:
            return LoginGuardDecision(allowed=True)
        if retry_after_seconds > 0:
            return LoginGuardDecision(
                allowed=False,
                retry_after_seconds=retry_after_seconds,
                detail=f"Too many failed login attempts. Try again in {retry_after_seconds} seconds.",
            )
        return LoginGuardDecision(allowed=True)

    def register_failure(self, request: Request, username: str) -> LoginGuardDecision:
        ip_address = self.get_client_ip(request)
        normalized_username = self._normalize_username(username)
        try:
            ip_failures = self._increment_window_counter(self._fail_ip_key(ip_address))
            user_failures = self._increment_window_counter(self._fail_user_key(normalized_username))
            if max(ip_failures, user_failures) < settings.auth_login_max_attempts:
                return LoginGuardDecision(allowed=True)

            self._redis_client().setex(self._ban_ip_key(ip_address), settings.auth_login_ban_seconds, "1")
            self._redis_client().setex(self._ban_user_key(normalized_username), settings.auth_login_ban_seconds, "1")
            self._redis_client().delete(self._fail_ip_key(ip_address), self._fail_user_key(normalized_username))
            return LoginGuardDecision(
                allowed=False,
                retry_after_seconds=settings.auth_login_ban_seconds,
                detail=f"Too many failed login attempts. Access is blocked for {settings.auth_login_ban_seconds} seconds.",
            )
        except RedisError:
            return LoginGuardDecision(allowed=True)

    def register_success(self, request: Request, username: str) -> None:
        ip_address = self.get_client_ip(request)
        normalized_username = self._normalize_username(username)
        try:
            self._redis_client().delete(self._fail_ip_key(ip_address), self._fail_user_key(normalized_username))
        except RedisError:
            return

    def _increment_window_counter(self, key: str) -> int:
        client = self._redis_client()
        current = int(client.incr(key))
        if current == 1:
            client.expire(key, settings.auth_login_window_seconds)
        return current

    def _get_ttl(self, key: str) -> int:
        ttl = int(self._redis_client().ttl(key))
        return ttl if ttl > 0 else 0

    def _redis_client(self) -> Redis[str]:
        if self._redis is None:
            self._redis = Redis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    def get_client_ip(self, request: Request) -> str:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        if forwarded_for.strip():
            return forwarded_for.split(",")[0].strip()
        if request.client and request.client.host:
            return request.client.host
        return "unknown"

    def _normalize_username(self, username: str) -> str:
        return (username or "").strip().lower() or "unknown"

    def _fail_ip_key(self, ip_address: str) -> str:
        return f"login_guard:fail:ip:{ip_address}"

    def _fail_user_key(self, username: str) -> str:
        return f"login_guard:fail:user:{username}"

    def _ban_ip_key(self, ip_address: str) -> str:
        return f"login_guard:ban:ip:{ip_address}"

    def _ban_user_key(self, username: str) -> str:
        return f"login_guard:ban:user:{username}"
