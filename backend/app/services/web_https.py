from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.schemas.settings import WebStatusRead
from app.services.app_settings import WebSettingsPayload


@dataclass
class WebConfigPreviewPayload:
    generated_nginx_config: str


class WebHttpsService:
    def normalize_domain(self, value: str | None) -> str | None:
        raw = (value or "").strip()
        if not raw:
            return None
        for prefix in ("https://", "http://"):
            if raw.startswith(prefix):
                raw = raw[len(prefix):]
        raw = raw.strip().strip("/")
        if "/" in raw:
            raw = raw.split("/", 1)[0].strip()
        return raw or None

    def generate_nginx_config(self, payload: WebSettingsPayload) -> str:
        domain = self.normalize_domain(payload.public_domain) or "panel.example.com"
        mode = (payload.web_mode or "http").strip().lower()
        if mode != "https":
            return (
                "server {\n"
                "    listen 80;\n"
                f"    server_name {domain};\n\n"
                "    client_max_body_size 2m;\n\n"
                "    location /api/ {\n"
                "        proxy_pass http://backend:8000/api/;\n"
                "        proxy_http_version 1.1;\n"
                "        proxy_set_header Host $host;\n"
                "        proxy_set_header X-Real-IP $remote_addr;\n"
                "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
                "        proxy_set_header X-Forwarded-Proto $scheme;\n"
                "    }\n\n"
                "    location / {\n"
                "        proxy_pass http://frontend:3000/;\n"
                "        proxy_http_version 1.1;\n"
                "        proxy_set_header Host $host;\n"
                "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
                "        proxy_set_header X-Forwarded-Proto $scheme;\n"
                "    }\n"
                "}\n"
            )
        return (
            "server {\n"
            "    listen 80;\n"
            f"    server_name {domain};\n\n"
            "    location /.well-known/acme-challenge/ {\n"
            "        root /var/www/certbot;\n"
            "    }\n\n"
            "    location / {\n"
            "        return 301 https://$host$request_uri;\n"
            "    }\n"
            "}\n\n"
            "server {\n"
            "    listen 443 ssl http2;\n"
            f"    server_name {domain};\n\n"
            f"    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;\n"
            f"    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;\n"
            "    client_max_body_size 2m;\n\n"
            "    location /api/ {\n"
            "        proxy_pass http://backend:8000/api/;\n"
            "        proxy_http_version 1.1;\n"
            "        proxy_set_header Host $host;\n"
            "        proxy_set_header X-Real-IP $remote_addr;\n"
            "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
            "        proxy_set_header X-Forwarded-Proto $scheme;\n"
            "    }\n\n"
            "    location / {\n"
            "        proxy_pass http://frontend:3000/;\n"
            "        proxy_http_version 1.1;\n"
            "        proxy_set_header Host $host;\n"
            "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
            "        proxy_set_header X-Forwarded-Proto $scheme;\n"
            "    }\n"
            "}\n"
        )

    def build_read_payload(self, payload: WebSettingsPayload) -> dict[str, Any]:
        normalized = self.normalize_domain(payload.public_domain)
        normalized_payload = WebSettingsPayload(
            public_domain=normalized,
            admin_email=payload.admin_email,
            web_mode=payload.web_mode,
        )
        return {
            "public_domain": normalized,
            "admin_email": payload.admin_email,
            "web_mode": payload.web_mode,
            "generated_nginx_config": self.generate_nginx_config(normalized_payload),
        }

    def get_status(self, payload: WebSettingsPayload) -> WebStatusRead:
        domain = self.normalize_domain(payload.public_domain)
        mode = (payload.web_mode or "http").strip().lower()
        if mode not in {"http", "https"}:
            mode = "http"
        if not domain:
            return WebStatusRead(
                public_domain=None,
                web_mode=mode,
                detail="Domain is not configured yet.",
            )

        resolved_ips: list[str] = []
        try:
            addr_info = socket.getaddrinfo(domain, None, proto=socket.IPPROTO_TCP)
            resolved_ips = sorted({item[4][0] for item in addr_info if item[4] and item[4][0]})
        except OSError as exc:
            return WebStatusRead(
                public_domain=domain,
                web_mode=mode,
                dns_ok=False,
                resolved_ips=[],
                detail=f"DNS lookup failed: {exc}",
            )

        port_80_open = self._can_connect(domain, 80)
        port_443_open = self._can_connect(domain, 443)
        certificate_present = False
        certificate_expires_at: str | None = None
        detail = None

        if port_443_open:
            try:
                cert = self._fetch_certificate(domain)
                certificate_present = cert is not None
                if cert and cert.get("notAfter"):
                    not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
                    certificate_expires_at = not_after.isoformat()
            except Exception as exc:  # noqa: BLE001
                detail = f"HTTPS is reachable, but certificate read failed: {exc}"
        elif mode == "https":
            detail = "HTTPS mode is selected, but port 443 is not reachable yet."

        if detail is None:
            if mode == "https" and certificate_present:
                detail = "HTTPS looks reachable and the certificate is readable."
            elif mode == "http" and port_80_open:
                detail = "HTTP looks reachable. HTTPS is optional until certificate issuance."
            else:
                detail = "DNS resolves, but the public web endpoint still needs finishing."

        return WebStatusRead(
            public_domain=domain,
            web_mode=mode,
            dns_ok=bool(resolved_ips),
            resolved_ips=resolved_ips,
            port_80_open=port_80_open,
            port_443_open=port_443_open,
            certificate_present=certificate_present,
            certificate_expires_at=certificate_expires_at,
            detail=detail,
        )

    def _can_connect(self, domain: str, port: int) -> bool:
        try:
            with socket.create_connection((domain, port), timeout=1.5):
                return True
        except OSError:
            return False

    def _fetch_certificate(self, domain: str) -> dict[str, Any] | None:
        context = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=2.0) as raw_socket:
            with context.wrap_socket(raw_socket, server_hostname=domain) as secure_socket:
                return secure_socket.getpeercert()
