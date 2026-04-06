from __future__ import annotations

import base64
import json
import mimetypes
import smtplib
import uuid
import ssl
from email.message import EmailMessage
from pathlib import Path
from urllib import parse, request

from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.server import Server
from app.models.service_instance import ServiceInstance
from app.models.delivery_log import DeliveryLog
from app.services.app_settings import AppSettingsService
from app.services.client_materials import ClientMaterialsService


class DeliveryService:
    def __init__(self) -> None:
        self.settings = AppSettingsService()
        self.materials = ClientMaterialsService()

    def _log(self, db: Session, *, client_id: int | None, channel: str, target: str, status: str, message: str | None = None, error_text: str | None = None) -> None:
        db.add(
            DeliveryLog(
                client_id=client_id,
                channel=channel,
                target=target,
                payload_type="client_configs",
                status=status,
                message=message,
                error_text=error_text,
            )
        )

    def _load_inline_asset(self, relative_path: str) -> bytes | None:
        asset_path = Path(__file__).resolve().parents[3] / relative_path
        if not asset_path.exists():
            return None
        return asset_path.read_bytes()

    def _parse_email_targets(self, raw_value: str | None) -> list[str]:
        if not raw_value:
            return []
        normalized = raw_value.replace("\r", "\n").replace(";", ",")
        parts: list[str] = []
        for line in normalized.split("\n"):
            for item in line.split(","):
                email = item.strip()
                if email:
                    parts.append(email)
        return parts

    def _open_smtp(self, host: str, port: int, *, username: str | None, password: str | None, use_tls: bool) -> smtplib.SMTP:
        timeout = 20
        if port == 465:
            smtp = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(host, port, timeout=timeout)
            if use_tls:
                smtp.starttls(context=ssl.create_default_context())
        if username:
            smtp.login(username, password or "")
        return smtp

    def _platform_links(self) -> list[dict[str, str]]:
        return [
            {
                "platform": "Windows",
                "url": "https://github.com/amnezia-vpn/amnezia-client/releases/latest",
                "hint": "Десктопный релиз / Desktop release",
            },
            {
                "platform": "macOS",
                "url": "https://github.com/amnezia-vpn/amnezia-client/releases/latest",
                "hint": "Десктопный релиз / Desktop release",
            },
            {
                "platform": "Linux",
                "url": "https://github.com/amnezia-vpn/amnezia-client/releases/latest",
                "hint": "Пакеты и релизы / Packages and releases",
            },
            {
                "platform": "Android",
                "url": "https://play.google.com/store/apps/details?id=org.amnezia.vpn",
                "hint": "Google Play",
            },
            {
                "platform": "iOS",
                "url": "https://apps.apple.com/us/app/amneziavpn/id1600529900",
                "hint": "App Store",
            },
        ]

    def _build_delivery_text(self, client: Client) -> str:
        lines = [
            f"Пакет доступа / Access package: {client.name}",
            f"IP: {client.assigned_ip}",
            "",
            "Вложенные файлы / Included files:",
            "- ubuntu-awg.conf",
            "- amneziawg.conf",
            "- amneziavpn.vpn",
            "",
            "Быстрый старт / Quick start:",
            "1. Установите AmneziaVPN или AmneziaWG на устройство. / Install AmneziaVPN or AmneziaWG on your device.",
            "2. Для основного приложения используйте файл amneziavpn.vpn. / Use amneziavpn.vpn for the main app.",
            "3. Для native AWG используйте amneziawg.conf или QR AmneziaWG. / Use amneziawg.conf or the AmneziaWG QR for native AWG import.",
            "4. Для Ubuntu и ручной настройки используйте ubuntu-awg.conf. / Use ubuntu-awg.conf for Ubuntu or manual setup.",
            "",
            "Ссылки / Downloads:",
        ]
        for item in self._platform_links():
            lines.append(f"- {item['platform']}: {item['url']}")
        return "\n".join(lines)

    def _build_delivery_html(self, client: Client, materials: dict[str, str | list[str] | None], image_cids: dict[str, str]) -> str:
        platform_rows = []
        for item in self._platform_links():
            platform_rows.append(
                f"""
                <tr>
                  <td style="padding:10px 0;border-bottom:1px solid #e7d9c1;font-weight:700;color:#1f2520;">{item["platform"]}</td>
                  <td style="padding:10px 0;border-bottom:1px solid #e7d9c1;color:#5c645c;">{item["hint"]}</td>
                  <td style="padding:10px 0;border-bottom:1px solid #e7d9c1;text-align:right;">
                    <a href="{item["url"]}" style="color:#b46a34;text-decoration:none;font-weight:700;">Открыть / Open</a>
                  </td>
                </tr>
                """
            )

        def logo_html(cid_key: str, fallback: str) -> str:
            cid = image_cids.get(cid_key)
            if cid:
                return (
                    f'<img src="cid:{cid}" alt="{fallback}" width="34" height="34" '
                    'style="display:block;border-radius:10px;">'
                )
            return (
                '<div style="width:34px;height:34px;border-radius:10px;background:#1d6b57;'
                'color:#fff7eb;display:flex;align-items:center;justify-content:center;'
                'font-size:12px;font-weight:700;">'
                f"{fallback}</div>"
            )

        def qr_card(title: str, subtitle: str, qr_key: str, logo_key: str, fallback: str) -> str:
            qr_cid = image_cids.get(qr_key)
            if not qr_cid:
                return ""
            return f"""
              <td valign="top" style="width:50%;padding:0 8px 0 0;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border:1px solid #d9cfbd;border-radius:18px;background:#fffdf8;">
                  <tr>
                    <td style="padding:18px;">
                      <table role="presentation" cellspacing="0" cellpadding="0">
                        <tr>
                          <td style="padding-right:12px;">{logo_html(logo_key, fallback)}</td>
                          <td>
                            <div style="font-size:18px;font-weight:700;color:#1f2520;">{title}</div>
                            <div style="font-size:13px;color:#5c645c;line-height:1.45;">{subtitle}</div>
                          </td>
                        </tr>
                      </table>
                      <div style="padding-top:18px;text-align:center;">
                        <img src="cid:{qr_cid}" alt="{title} QR" width="220" height="220" style="display:inline-block;border:1px solid #e7d9c1;border-radius:14px;background:#ffffff;padding:12px;">
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            """

        qr_grid = (
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>'
            + qr_card(
                "QR для AmneziaWG / AmneziaWG QR",
                "Сканируйте в AmneziaWG или импортируйте .conf файл. / Scan in AmneziaWG or import the .conf file.",
                "amneziawg_qr",
                "amneziawg_logo",
                "WG",
            )
            + qr_card(
                "QR для AmneziaVPN / AmneziaVPN QR",
                "Сканируйте в приложении AmneziaVPN или откройте .vpn файл. / Scan in AmneziaVPN or open the attached .vpn file.",
                "amneziavpn_qr",
                "amneziavpn_logo",
                "VPN",
            )
            + "</tr></table>"
        )

        return f"""\
<!DOCTYPE html>
<html lang="ru">
  <body style="margin:0;padding:0;background:#f5f1e8;color:#1f2520;font-family:Georgia,'Times New Roman',serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f5f1e8;padding:28px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="760" cellspacing="0" cellpadding="0" style="width:760px;max-width:760px;background:#fffaf2;border:1px solid #d9cfbd;box-shadow:0 20px 48px rgba(73,57,41,0.10);">
            <tr>
              <td style="padding:28px;background:linear-gradient(90deg, rgba(255,250,242,1) 0%, rgba(247,241,228,1) 62%, rgba(235,220,190,0.9) 100%);border-bottom:1px solid #e7d9c1;">
                <div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;color:#b46a34;">AWG Control Panel</div>
                <div style="padding-top:10px;font-size:34px;line-height:1.1;font-weight:700;color:#1f2520;">Пакет доступа / Access package for {client.name}</div>
                <div style="padding-top:10px;font-size:16px;color:#5c645c;">Назначенный IP / Assigned IP: {client.assigned_ip}</div>
              </td>
            </tr>
            <tr>
              <td style="padding:26px 28px 0;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border:1px solid #d9cfbd;background:#fffdf8;">
                  <tr>
                    <td style="padding:18px 20px;">
                      <div style="font-size:20px;font-weight:700;color:#1f2520;">Быстрый старт / Quick start</div>
                      <ol style="margin:14px 0 0;padding-left:20px;color:#5c645c;line-height:1.7;">
                        <li>Установите AmneziaVPN или AmneziaWG на устройство. / Install AmneziaVPN or AmneziaWG on your device.</li>
                        <li>Для основного приложения используйте <strong>amneziavpn.vpn</strong> или QR AmneziaVPN. / Use <strong>amneziavpn.vpn</strong> or the AmneziaVPN QR for the main app.</li>
                        <li>Для native AWG используйте <strong>amneziawg.conf</strong> или QR AmneziaWG. / Use <strong>amneziawg.conf</strong> or the AmneziaWG QR for native AWG import.</li>
                        <li>Для Ubuntu и ручного импорта используйте <strong>ubuntu-awg.conf</strong>. / Use <strong>ubuntu-awg.conf</strong> for Ubuntu or manual setup.</li>
                      </ol>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 28px 0;">
                <div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;color:#b46a34;padding-bottom:10px;">QR коды / QR codes</div>
                {qr_grid}
              </td>
            </tr>
            <tr>
              <td style="padding:24px 28px 0;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border:1px solid #d9cfbd;background:#fffdf8;">
                  <tr>
                    <td style="padding:18px 20px;">
                      <div style="font-size:20px;font-weight:700;color:#1f2520;">Файлы / Included files</div>
                      <ul style="margin:14px 0 0;padding-left:20px;color:#5c645c;line-height:1.75;">
                        <li><strong>ubuntu-awg.conf</strong> — Ubuntu и ручной импорт / Ubuntu and manual import.</li>
                        <li><strong>amneziawg.conf</strong> — native конфиг AmneziaWG / native AmneziaWG config.</li>
                        <li><strong>amneziavpn.vpn</strong> — профиль AmneziaVPN / AmneziaVPN profile.</li>
                      </ul>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 28px 28px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border:1px solid #d9cfbd;background:#fffdf8;">
                  <tr>
                    <td style="padding:18px 20px;">
                      <div style="font-size:20px;font-weight:700;color:#1f2520;">Приложения и загрузки / Applications and downloads</div>
                      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:14px;">
                        {''.join(platform_rows)}
                      </table>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

    def _send_email(self, db: Session, client: Client, target_email: str) -> None:
        settings = self.settings.get_delivery_settings(db)
        if not settings.delivery_email_enabled:
            raise RuntimeError("Email delivery is disabled")
        if not settings.smtp_host or not settings.smtp_from_email or not settings.smtp_password:
            raise RuntimeError("SMTP settings are incomplete")
        materials = self.materials.decrypt_materials(client)

        msg = EmailMessage()
        msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>" if settings.smtp_from_name else settings.smtp_from_email
        msg["To"] = target_email
        msg["Subject"] = f"AWG access for {client.name}"
        msg.set_content(self._build_delivery_text(client))

        inline_assets: dict[str, tuple[str, bytes, str]] = {}
        asset_sources = {
            "amneziawg_logo": ("frontend/logo/amWG.png", "image/png"),
            "amneziavpn_logo": ("frontend/logo/amvpn.png", "image/png"),
        }
        for key, (relative_path, content_type) in asset_sources.items():
            asset_bytes = self._load_inline_asset(relative_path)
            if asset_bytes:
                inline_assets[key] = (key, asset_bytes, content_type)

        qr_sources = {
            "amneziawg_qr": materials.get("amneziawg_qr_png_base64"),
            "amneziavpn_qr": materials.get("amneziavpn_qr_png_base64"),
        }
        for key, value in qr_sources.items():
            if isinstance(value, str) and value:
                inline_assets[key] = (key, base64.b64decode(value.encode("utf-8")), "image/png")

        html = self._build_delivery_html(
            client,
            materials,
            {key: cid for key, (cid, _, _) in inline_assets.items()},
        )
        msg.add_alternative(html, subtype="html")
        html_part = msg.get_body(preferencelist=("html",))
        if html_part is not None:
            for cid, content, content_type in inline_assets.values():
                maintype, subtype = content_type.split("/", maxsplit=1)
                html_part.add_related(content, maintype=maintype, subtype=subtype, cid=f"<{cid}>")

        attachments = [
            ("ubuntu-awg.conf", materials.get("ubuntu_config"), "text/plain"),
            ("amneziawg.conf", materials.get("amneziawg_config"), "text/plain"),
            ("amneziavpn.vpn", materials.get("amneziavpn_config"), "application/octet-stream"),
        ]
        for filename, content, content_type in attachments:
            if not content:
                continue
            maintype, subtype = content_type.split("/", maxsplit=1)
            msg.add_attachment(content.encode("utf-8"), maintype=maintype, subtype=subtype, filename=filename)

        with self._open_smtp(
            settings.smtp_host,
            settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
        ) as smtp:
            smtp.send_message(msg)

    def _send_text_email(self, db: Session, target_email: str, subject: str, text: str) -> None:
        settings = self.settings.get_delivery_settings(db)
        if not settings.smtp_host or not settings.smtp_from_email or not settings.smtp_password:
            return
        msg = EmailMessage()
        msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>" if settings.smtp_from_name else settings.smtp_from_email
        msg["To"] = target_email
        msg["Subject"] = subject
        msg.set_content(text)
        with self._open_smtp(
            settings.smtp_host,
            settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
        ) as smtp:
            smtp.send_message(msg)

    def _build_mtproxy_delivery_text(self, service: ServiceInstance, server: Server) -> str:
        config: dict[str, object] = {}
        if service.config_json:
            try:
                loaded = json.loads(service.config_json)
                if isinstance(loaded, dict):
                    config = loaded
            except json.JSONDecodeError:
                config = {}
        tg_url = str(config.get("tg_url") or "")
        domain = str(config.get("domain") or "")
        port = str(config.get("port") or "443")
        lines = [
            "Доступ к MTProxy / MTProxy access",
            "",
            f"Сервер / Server: {server.name} ({server.host})",
            f"Порт / Port: {port}",
            f"Endpoint: {service.public_endpoint or f'{server.host}:{port}'}",
            f"Fake TLS domain: {domain or '-'}",
            "",
            "Быстрый старт / Quick start:",
            "1. Откройте Telegram на устройстве. / Open Telegram on your device.",
            "2. Перейдите по ссылке MTProxy ниже. / Open the MTProxy link below.",
            "3. Подтвердите подключение к прокси в Telegram. / Confirm proxy setup in Telegram.",
        ]
        if tg_url:
            lines.extend(["", f"MTProxy link: {tg_url}"])
        else:
            lines.extend(["", "MTProxy link is not available in panel yet."])
        return "\n".join(lines)

    def _build_socks5_delivery_text(self, service: ServiceInstance, server: Server) -> str:
        config: dict[str, object] = {}
        if service.config_json:
            try:
                loaded = json.loads(service.config_json)
                if isinstance(loaded, dict):
                    config = loaded
            except json.JSONDecodeError:
                config = {}
        port = str(config.get("port") or "1080")
        username = str(config.get("username") or "")
        password = str(config.get("password") or "")
        endpoint = service.public_endpoint or f"{server.host}:{port}"
        lines = [
            "Доступ к SOCKS5 / SOCKS5 access",
            "",
            f"Сервер / Server: {server.name} ({server.host})",
            f"Порт / Port: {port}",
            f"Endpoint: {endpoint}",
            f"Логин / Username: {username or '-'}",
            f"Пароль / Password: {password or '-'}",
            "",
            "Быстрый старт / Quick start:",
            "1. Откройте настройки прокси в приложении или системе. / Open proxy settings in your app or system.",
            "2. Выберите SOCKS5. / Select SOCKS5.",
            f"3. Укажите сервер {server.host} и порт {port}. / Set host {server.host} and port {port}.",
        ]
        if username and password:
            lines.append("4. Введите логин и пароль из письма. / Enter the username and password from this email.")
        lines.extend(
            [
                "",
                "Пример URI / Example URI:",
                f"socks5://{username}:{password}@{server.host}:{port}" if username and password else f"socks5://{server.host}:{port}",
            ]
        )
        return "\n".join(lines)

    def _build_xray_delivery_text(self, service: ServiceInstance, server: Server) -> str:
        config: dict[str, object] = {}
        if service.config_json:
            try:
                loaded = json.loads(service.config_json)
                if isinstance(loaded, dict):
                    config = loaded
            except json.JSONDecodeError:
                config = {}
        port = str(config.get("port") or "443")
        server_name = str(config.get("server_name") or "")
        public_key = str(config.get("public_key") or "")
        short_id = str(config.get("short_id") or "")
        uuid_value = str(config.get("uuid") or "")
        client_uri = str(config.get("client_uri") or "")
        lines = [
            "Доступ к Xray / VLESS + Reality",
            "",
            f"Сервер / Server: {server.name} ({server.host})",
            f"Порт / Port: {port}",
            f"SNI / Server name: {server_name or '-'}",
            f"UUID: {uuid_value or '-'}",
            f"Public key: {public_key or '-'}",
            f"Short ID: {short_id or '-'}",
            "",
            "Быстрый старт / Quick start:",
            "1. Откройте iPhone-клиент с поддержкой VLESS + Reality. / Open an iPhone client which supports VLESS + Reality.",
            "2. Импортируйте ссылку ниже. / Import the link below.",
        ]
        if client_uri:
            lines.extend(["", f"VLESS link: {client_uri}"])
        return "\n".join(lines)

    def send_mtproxy_email(self, db: Session, service: ServiceInstance, server: Server, target_email: str) -> str:
        settings = self.settings.get_delivery_settings(db)
        if not settings.delivery_email_enabled:
            raise RuntimeError("Email delivery is disabled")
        if not settings.smtp_host or not settings.smtp_from_email or not settings.smtp_password:
            raise RuntimeError("SMTP settings are incomplete")
        self._send_text_email(
            db,
            target_email,
            f"MTProxy access for {server.name}",
            self._build_mtproxy_delivery_text(service, server),
        )
        return f"MTProxy access sent to {target_email}"

    def send_socks5_email(self, db: Session, service: ServiceInstance, server: Server, target_email: str) -> str:
        settings = self.settings.get_delivery_settings(db)
        if not settings.delivery_email_enabled:
            raise RuntimeError("Email delivery is disabled")
        if not settings.smtp_host or not settings.smtp_from_email or not settings.smtp_password:
            raise RuntimeError("SMTP settings are incomplete")
        self._send_text_email(
            db,
            target_email,
            f"SOCKS5 access for {server.name}",
            self._build_socks5_delivery_text(service, server),
        )
        return f"SOCKS5 access sent to {target_email}"

    def send_xray_email(self, db: Session, service: ServiceInstance, server: Server, target_email: str) -> str:
        settings = self.settings.get_delivery_settings(db)
        if not settings.delivery_email_enabled:
            raise RuntimeError("Email delivery is disabled")
        if not settings.smtp_host or not settings.smtp_from_email or not settings.smtp_password:
            raise RuntimeError("SMTP settings are incomplete")
        self._send_text_email(
            db,
            target_email,
            f"Xray access for {server.name}",
            self._build_xray_delivery_text(service, server),
        )
        return f"Xray access sent to {target_email}"

    def send_test_email(self, db: Session) -> str:
        settings = self.settings.get_delivery_settings(db)
        if not settings.smtp_host or not settings.smtp_from_email or not settings.smtp_password:
            raise RuntimeError("SMTP settings are incomplete")
        targets = self._parse_email_targets(settings.admin_notification_email)
        if not targets:
            raise RuntimeError("Admin notification email is not configured")
        for target in targets:
            self._send_text_email(
                db,
                target,
                "AWG panel email delivery test",
                "This is a test email from AWG Control Panel delivery settings.",
            )
        return f"Test email sent to {', '.join(targets)}"

    def _telegram_request(self, token: str, method: str, fields: dict[str, str], files: list[tuple[str, str, bytes]] | None = None) -> dict[str, object]:
        if files:
            boundary = f"awg-{uuid.uuid4().hex}"
            body = bytearray()
            for key, value in fields.items():
                body.extend(f"--{boundary}\r\n".encode())
                body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
                body.extend(f"{value}\r\n".encode())
            for field_name, filename, content in files:
                mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
                body.extend(f"--{boundary}\r\n".encode())
                body.extend(f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode())
                body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode())
                body.extend(content)
                body.extend(b"\r\n")
            body.extend(f"--{boundary}--\r\n".encode())
            req = request.Request(
                f"https://api.telegram.org/bot{token}/{method}",
                data=bytes(body),
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST",
            )
        else:
            req = request.Request(
                f"https://api.telegram.org/bot{token}/{method}",
                data=parse.urlencode(fields).encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
        with request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def _send_telegram(self, db: Session, client: Client, chat_id: str) -> None:
        settings = self.settings.get_delivery_settings(db)
        if not settings.delivery_telegram_enabled:
            raise RuntimeError("Telegram delivery is disabled")
        if not settings.telegram_bot_token:
            raise RuntimeError("Telegram bot token is not configured")
        materials = self.materials.decrypt_materials(client)
        text_lines = [
            f"Пакет доступа / AWG access for {client.name}",
            f"IP: {client.assigned_ip}",
            "",
            "Быстрый старт / Quick start:",
            "1. Используйте amneziavpn.vpn в приложении AmneziaVPN. / Use amneziavpn.vpn in the AmneziaVPN app.",
            "2. Используйте amneziawg.conf или QR AmneziaWG для native AWG. / Use amneziawg.conf or the AmneziaWG QR for native AWG import.",
            "3. Используйте ubuntu-awg.conf для Ubuntu и ручной настройки. / Use ubuntu-awg.conf for Ubuntu or manual setup.",
            "",
            "Ссылки / Downloads:",
        ]
        for item in self._platform_links():
            text_lines.append(f"{item['platform']}: {item['url']}")
        self._telegram_request(
            settings.telegram_bot_token,
            "sendMessage",
            {"chat_id": chat_id, "text": "\n".join(text_lines)},
        )
        for caption, qr_content in [
            ("QR для AmneziaWG / AmneziaWG QR", materials.get("amneziawg_qr_png_base64")),
            ("QR для AmneziaVPN / AmneziaVPN QR", materials.get("amneziavpn_qr_png_base64")),
        ]:
            if not isinstance(qr_content, str) or not qr_content:
                continue
            self._telegram_request(
                settings.telegram_bot_token,
                "sendPhoto",
                {"chat_id": chat_id, "caption": caption},
                files=[("photo", f"{caption.lower().replace(' ', '-')}.png", base64.b64decode(qr_content.encode("utf-8")))],
            )
        for filename, content in [
            ("ubuntu-awg.conf", materials.get("ubuntu_config")),
            ("amneziawg.conf", materials.get("amneziawg_config")),
            ("amneziavpn.vpn", materials.get("amneziavpn_config")),
        ]:
            if not content:
                continue
            self._telegram_request(
                settings.telegram_bot_token,
                "sendDocument",
                {"chat_id": chat_id},
                files=[("document", filename, content.encode("utf-8"))],
            )

    def send_test_telegram(self, db: Session) -> str:
        settings = self.settings.get_delivery_settings(db)
        if not settings.telegram_bot_token:
            raise RuntimeError("Telegram bot token is not configured")
        if not settings.telegram_admin_chat_id:
            raise RuntimeError("Telegram admin chat id is not configured")
        self._telegram_request(
            settings.telegram_bot_token,
            "sendMessage",
            {
                "chat_id": settings.telegram_admin_chat_id,
                "text": "AWG Control Panel Telegram delivery test.",
            },
        )
        return f"Test Telegram message sent to {settings.telegram_admin_chat_id}"

    def deliver_client_configs(self, db: Session, client: Client, channels: list[str]) -> dict[str, str]:
        if client.archived:
            raise RuntimeError("Archived client delivery is unavailable")
        result: dict[str, str] = {}
        settings = self.settings.get_delivery_settings(db)
        requested_channels = channels or ["email", "telegram"]
        if "email" in requested_channels:
            if not client.delivery_email:
                result["email"] = "skipped"
            else:
                try:
                    self._send_email(db, client, client.delivery_email)
                    self._log(db, client_id=client.id, channel="email", target=client.delivery_email, status="sent")
                    result["email"] = "sent"
                except Exception as exc:  # noqa: BLE001
                    self._log(db, client_id=client.id, channel="email", target=client.delivery_email, status="failed", error_text=str(exc))
                    result["email"] = f"failed: {exc}"
        if "telegram" in requested_channels:
            if not client.delivery_telegram_chat_id:
                result["telegram"] = "skipped"
            else:
                try:
                    self._send_telegram(db, client, client.delivery_telegram_chat_id)
                    self._log(db, client_id=client.id, channel="telegram", target=client.delivery_telegram_chat_id, status="sent")
                    result["telegram"] = "sent"
                except Exception as exc:  # noqa: BLE001
                    self._log(db, client_id=client.id, channel="telegram", target=client.delivery_telegram_chat_id, status="failed", error_text=str(exc))
                    result["telegram"] = f"failed: {exc}"
        db.commit()
        notification_text = f"Manual config delivery for {client.name}: {result}"
        if settings.admin_email_notifications_enabled:
            for target in self._parse_email_targets(settings.admin_notification_email):
                try:
                    self._send_text_email(db, target, "AWG panel notification", notification_text)
                except Exception:
                    pass
        if settings.admin_telegram_notifications_enabled and settings.telegram_admin_chat_id and settings.telegram_bot_token:
            try:
                self._telegram_request(
                    settings.telegram_bot_token,
                    "sendMessage",
                    {"chat_id": settings.telegram_admin_chat_id, "text": notification_text},
                )
            except Exception:
                pass
        return result
