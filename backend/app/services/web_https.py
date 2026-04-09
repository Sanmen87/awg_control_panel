from __future__ import annotations

import socket
import ssl
import subprocess
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from app.core.config import settings as app_config
from app.schemas.settings import WebApplyResult
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


class WebHttpsApplyService:
    def __init__(self) -> None:
        self.inspect_service = WebHttpsService()
        self.nginx_conf_path = Path(app_config.web_runtime_nginx_conf_path)
        self.acme_webroot = Path(app_config.web_runtime_acme_webroot)
        self.letsencrypt_path = Path(app_config.web_runtime_letsencrypt_path)
        self.compose_project_name = app_config.compose_project_name

    def apply(self, payload: WebSettingsPayload) -> WebApplyResult:
        domain = self.inspect_service.normalize_domain(payload.public_domain)
        mode = (payload.web_mode or "http").strip().lower()
        if mode not in {"http", "https"}:
            mode = "http"
        if not domain:
            raise ValueError("Public domain is required before applying web settings.")

        if mode == "https" and not (payload.admin_email or "").strip():
            raise ValueError("Email for Let's Encrypt is required in HTTPS mode.")

        self._ensure_runtime_paths()

        if mode == "https":
            self._write_nginx_config(self._generate_acme_bootstrap_config(domain))
            self._reload_nginx()
            self._run_certbot(domain, (payload.admin_email or "").strip())

        final_payload = WebSettingsPayload(
            public_domain=domain,
            admin_email=(payload.admin_email or "").strip() or None,
            web_mode=mode,
        )
        self._write_nginx_config(self.inspect_service.generate_nginx_config(final_payload))
        self._reload_nginx()

        status = self.inspect_service.get_status(final_payload)
        return WebApplyResult(
            public_domain=domain,
            web_mode=mode,
            nginx_reloaded=True,
            certificate_requested=mode == "https",
            certificate_present=status.certificate_present,
            certificate_expires_at=status.certificate_expires_at,
            detail=status.detail or "Web settings applied.",
        )

    def _ensure_runtime_paths(self) -> None:
        self.nginx_conf_path.parent.mkdir(parents=True, exist_ok=True)
        self.acme_webroot.mkdir(parents=True, exist_ok=True)
        self.letsencrypt_path.mkdir(parents=True, exist_ok=True)

    def _write_nginx_config(self, content: str) -> None:
        self.nginx_conf_path.write_text(content, encoding="utf-8")

    def _reload_nginx(self) -> None:
        container_id = self._find_nginx_container_id()
        if not container_id:
            raise RuntimeError("Could not find nginx container to reload.")
        self._docker_api_request(
            "POST",
            f"/containers/{container_id}/kill",
            {"signal": "HUP"},
            "Failed to reload nginx container",
            expected_statuses={204},
        )

    def _find_nginx_container_id(self) -> str | None:
        containers = self._docker_api_request(
            "GET",
            "/containers/json",
            {"all": "0"},
            "Failed to query running nginx container",
            expected_statuses={200},
        )
        if not isinstance(containers, list) or not containers:
            return None
        for container in containers:
            if not isinstance(container, dict):
                continue
            labels = container.get("Labels") or {}
            names = container.get("Names") or []
            if not isinstance(labels, dict) or not isinstance(names, list):
                continue

            compose_service = labels.get("com.docker.compose.service")
            compose_project = labels.get("com.docker.compose.project")
            if compose_service == "nginx" and (
                compose_project == self.compose_project_name or not self.compose_project_name
            ):
                container_id = container.get("Id")
                if isinstance(container_id, str) and container_id:
                    return container_id

            normalized_names = [name.lstrip("/") for name in names if isinstance(name, str)]
            for name in normalized_names:
                if "nginx" not in name:
                    continue
                if self.compose_project_name and self.compose_project_name not in name:
                    continue
                container_id = container.get("Id")
                if isinstance(container_id, str) and container_id:
                    return container_id

        for container in containers:
            if not isinstance(container, dict):
                continue
            names = container.get("Names") or []
            if not isinstance(names, list):
                continue
            normalized_names = [name.lstrip("/") for name in names if isinstance(name, str)]
            if any("nginx" in name for name in normalized_names):
                container_id = container.get("Id")
                if isinstance(container_id, str) and container_id:
                    return container_id

        return None

    def _run_certbot(self, domain: str, email: str) -> None:
        self._run_command(
            [
                "certbot",
                "certonly",
                "--webroot",
                "-w",
                str(self.acme_webroot),
                "-d",
                domain,
                "--email",
                email,
                "--agree-tos",
                "--non-interactive",
                "--keep-until-expiring",
            ],
            "Failed to issue or renew Let's Encrypt certificate",
        )

    def _generate_acme_bootstrap_config(self, domain: str) -> str:
        return (
            "server {\n"
            "    listen 80;\n"
            f"    server_name {domain};\n\n"
            "    client_max_body_size 2m;\n\n"
            "    location /.well-known/acme-challenge/ {\n"
            f"        root {self.acme_webroot};\n"
            "    }\n\n"
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

    def _run_command(self, command: list[str], error_prefix: str) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(command, check=False, capture_output=True, text=True)
        except OSError as exc:
            raise RuntimeError(f"{error_prefix}: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"{error_prefix}: {detail or 'unknown error'}")
        return result

    def _docker_api_request(
        self,
        method: str,
        path: str,
        query: dict[str, str] | None,
        error_prefix: str,
        *,
        expected_statuses: set[int],
    ) -> Any:
        request_path = path
        if query:
            request_path = f"{path}?{urlencode(query)}"

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(5.0)
                client.connect("/var/run/docker.sock")
                request = (
                    f"{method} {request_path} HTTP/1.1\r\n"
                    "Host: docker\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                client.sendall(request.encode("utf-8"))
                chunks: list[bytes] = []
                while True:
                    chunk = client.recv(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
        except OSError as exc:
            raise RuntimeError(f"{error_prefix}: {exc}") from exc

        raw_response = b"".join(chunks)
        header_bytes, _, body_bytes = raw_response.partition(b"\r\n\r\n")
        header_lines = header_bytes.decode("utf-8", errors="replace").split("\r\n")
        if not header_lines:
            raise RuntimeError(f"{error_prefix}: empty response from Docker API")
        status_line = header_lines[0].split(" ", 2)
        if len(status_line) < 2 or not status_line[1].isdigit():
            raise RuntimeError(f"{error_prefix}: malformed response from Docker API")
        status_code = int(status_line[1])
        if status_code not in expected_statuses:
            detail = body_bytes.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"{error_prefix}: {detail or f'Docker API status {status_code}'}")
        if not body_bytes.strip():
            return None
        try:
            return json.loads(body_bytes.decode("utf-8"))
        except json.JSONDecodeError:
            return body_bytes.decode("utf-8", errors="replace")
