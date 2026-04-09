from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.app_settings import WebSettingsPayload


@dataclass
class WebStatusPayload:
    public_domain: str | None
    web_mode: str
    dns_ok: bool
    resolved_ips: list[str]
    port_80_open: bool
    port_443_open: bool
    certificate_present: bool
    certificate_expires_at: str | None
    detail: str | None


class WebSettingsService:
    def render_nginx_config(self, settings: WebSettingsPayload) -> str:
        domain = settings.public_domain or "panel.example.com"
        if settings.web_mode == "https":
            return f"""server {{
    listen 80;
    server_name {domain};

    location /.well-known/acme-challenge/ {{
        root /var/www/certbot;
    }}

    location / {{
        return 301 https://$host$request_uri;
    }}
}}

server {{
    listen 443 ssl http2;
    server_name {domain};

    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;

    client_max_body_size 2m;

    location /api/ {{
        proxy_pass http://backend:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}

    location / {{
        proxy_pass http://frontend:3000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""

        return f"""server {{
    listen 80;
    server_name {domain};

    client_max_body_size 2m;

    location /api/ {{
        proxy_pass http://backend:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}

    location / {{
        proxy_pass http://frontend:3000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""

    def inspect(self, settings: WebSettingsPayload) -> WebStatusPayload:
        domain = settings.public_domain
        if not domain:
            return WebStatusPayload(
                public_domain=None,
                web_mode=settings.web_mode,
                dns_ok=False,
                resolved_ips=[],
                port_80_open=False,
                port_443_open=False,
                certificate_present=False,
                certificate_expires_at=None,
                detail="Public domain is not configured yet.",
            )

        resolved_ips: list[str] = []
        dns_ok = False
        port_80_open = False
        port_443_open = False
        certificate_present = False
        certificate_expires_at: str | None = None
        detail: str | None = None

        try:
            infos = socket.getaddrinfo(domain, None, type=socket.SOCK_STREAM)
            for item in infos:
                host = item[4][0]
                if host not in resolved_ips:
                    resolved_ips.append(host)
            dns_ok = bool(resolved_ips)
        except OSError as exc:
            detail = f"DNS lookup failed: {exc}"

        if dns_ok:
            port_80_open = self._is_port_open(domain, 80)
            port_443_open = self._is_port_open(domain, 443)
            certificate_present, certificate_expires_at, cert_detail = self._inspect_certificate(domain)
            if cert_detail:
                detail = cert_detail

        return WebStatusPayload(
            public_domain=domain,
            web_mode=settings.web_mode,
            dns_ok=dns_ok,
            resolved_ips=resolved_ips,
            port_80_open=port_80_open,
            port_443_open=port_443_open,
            certificate_present=certificate_present,
            certificate_expires_at=certificate_expires_at,
            detail=detail,
        )

    def _is_port_open(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=3):
                return True
        except OSError:
            return False

    def _inspect_certificate(self, host: str) -> tuple[bool, str | None, str | None]:
        try:
            context = ssl.create_default_context()
            with socket.create_connection((host, 443), timeout=3) as sock:
                with context.wrap_socket(sock, server_hostname=host) as tls_sock:
                    cert = tls_sock.getpeercert()
        except OSError as exc:
            return False, None, f"TLS certificate check failed: {exc}"
        except ssl.SSLError as exc:
            return False, None, f"TLS certificate check failed: {exc}"

        not_after = cert.get("notAfter")
        if not not_after:
            return True, None, None
        try:
            parsed = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
        except ValueError:
            return True, not_after, None
        return True, parsed.isoformat(), None
