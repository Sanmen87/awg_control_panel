from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.security import decrypt_value, encrypt_value
from app.models.app_setting import AppSetting


@dataclass
class DeliverySettingsPayload:
    delivery_email_enabled: bool = False
    delivery_telegram_enabled: bool = False
    admin_email_notifications_enabled: bool = False
    admin_telegram_notifications_enabled: bool = False
    notification_level: str = "important_only"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_from_name: str | None = None
    smtp_use_tls: bool = True
    telegram_bot_token: str | None = None
    telegram_admin_chat_id: str | None = None
    admin_notification_email: str | None = None


@dataclass
class BackupSettingsPayload:
    auto_backup_enabled: bool = False
    auto_backup_hour_utc: int = 3
    backup_retention_days: int = 14


@dataclass
class WebSettingsPayload:
    public_domain: str | None = None
    admin_email: str | None = None
    web_mode: str = "http"


class AppSettingsService:
    NOTIFICATION_LEVEL_ALIASES: dict[str, str] = {
        "delivery_only": "important_only",
        "client_lifecycle": "access_changes",
        "policy_alerts": "policy_and_expiry",
        "system_alerts": "full_monitoring",
    }

    DELIVERY_KEYS: dict[str, bool] = {
        "delivery_email_enabled": False,
        "delivery_telegram_enabled": False,
        "admin_email_notifications_enabled": False,
        "admin_telegram_notifications_enabled": False,
        "notification_level": False,
        "smtp_host": False,
        "smtp_port": False,
        "smtp_username": False,
        "smtp_password": True,
        "smtp_from_email": False,
        "smtp_from_name": False,
        "smtp_use_tls": False,
        "telegram_bot_token": True,
        "telegram_admin_chat_id": False,
        "admin_notification_email": False,
    }
    BACKUP_KEYS: dict[str, bool] = {
        "auto_backup_enabled": False,
        "auto_backup_hour_utc": False,
        "backup_retention_days": False,
        "last_auto_backup_date": False,
        "last_backup_cleanup_date": False,
    }
    WEB_KEYS: dict[str, bool] = {
        "web_public_domain": False,
        "web_admin_email": False,
        "web_mode": False,
    }

    def _get_setting(self, db: Session, key: str) -> AppSetting | None:
        return db.query(AppSetting).filter(AppSetting.key == key).first()

    def _get_value(self, setting: AppSetting | None) -> str | None:
        if not setting or setting.value_text is None:
            return None
        return decrypt_value(setting.value_text) if setting.is_encrypted else setting.value_text

    def _bool(self, value: str | None, default: bool = False) -> bool:
        if value is None:
            return default
        return value.lower() in {"1", "true", "yes", "on"}

    def _normalize_notification_level(self, value: str | None) -> str:
        raw = (value or "").strip() or "important_only"
        return self.NOTIFICATION_LEVEL_ALIASES.get(raw, raw)

    def get_delivery_settings(self, db: Session) -> DeliverySettingsPayload:
        values = {key: self._get_value(self._get_setting(db, key)) for key in self.DELIVERY_KEYS}
        return DeliverySettingsPayload(
            delivery_email_enabled=self._bool(values["delivery_email_enabled"]),
            delivery_telegram_enabled=self._bool(values["delivery_telegram_enabled"]),
            admin_email_notifications_enabled=self._bool(values["admin_email_notifications_enabled"]),
            admin_telegram_notifications_enabled=self._bool(values["admin_telegram_notifications_enabled"]),
            notification_level=self._normalize_notification_level(values["notification_level"]),
            smtp_host=values["smtp_host"],
            smtp_port=int(values["smtp_port"] or 587),
            smtp_username=values["smtp_username"],
            smtp_password=values["smtp_password"],
            smtp_from_email=values["smtp_from_email"],
            smtp_from_name=values["smtp_from_name"],
            smtp_use_tls=self._bool(values["smtp_use_tls"], True),
            telegram_bot_token=values["telegram_bot_token"],
            telegram_admin_chat_id=values["telegram_admin_chat_id"],
            admin_notification_email=values["admin_notification_email"],
        )

    def get_backup_settings(self, db: Session) -> BackupSettingsPayload:
        values = {key: self._get_value(self._get_setting(db, key)) for key in self.BACKUP_KEYS}
        auto_backup_hour_utc = int(values["auto_backup_hour_utc"] or 3)
        backup_retention_days = int(values["backup_retention_days"] or 14)
        auto_backup_hour_utc = min(max(auto_backup_hour_utc, 0), 23)
        backup_retention_days = max(1, backup_retention_days)
        return BackupSettingsPayload(
            auto_backup_enabled=self._bool(values["auto_backup_enabled"]),
            auto_backup_hour_utc=auto_backup_hour_utc,
            backup_retention_days=backup_retention_days,
        )

    def update_delivery_settings(self, db: Session, payload: DeliverySettingsPayload) -> DeliverySettingsPayload:
        payload.notification_level = self._normalize_notification_level(payload.notification_level)
        for key, encrypted in self.DELIVERY_KEYS.items():
            value = getattr(payload, key)
            if key in {"smtp_password", "telegram_bot_token"} and value is None:
                continue
            setting = self._get_setting(db, key) or AppSetting(key=key, is_encrypted=encrypted)
            if isinstance(value, bool):
                text_value = "true" if value else "false"
            elif isinstance(value, int):
                text_value = str(value)
            else:
                text_value = (value or "").strip() or None
            setting.value_text = encrypt_value(text_value) if encrypted and text_value is not None else text_value
            setting.is_encrypted = encrypted
            db.add(setting)
        db.commit()
        return self.get_delivery_settings(db)

    def update_backup_settings(self, db: Session, payload: BackupSettingsPayload) -> BackupSettingsPayload:
        payload.auto_backup_hour_utc = min(max(int(payload.auto_backup_hour_utc), 0), 23)
        payload.backup_retention_days = max(1, int(payload.backup_retention_days))
        for key in ("auto_backup_enabled", "auto_backup_hour_utc", "backup_retention_days"):
            value = getattr(payload, key)
            setting = self._get_setting(db, key) or AppSetting(key=key, is_encrypted=False)
            if isinstance(value, bool):
                text_value = "true" if value else "false"
            else:
                text_value = str(value)
            setting.value_text = text_value
            setting.is_encrypted = False
            db.add(setting)
        db.commit()
        return self.get_backup_settings(db)

    def get_web_settings(self, db: Session) -> WebSettingsPayload:
        values = {key: self._get_value(self._get_setting(db, key)) for key in self.WEB_KEYS}
        mode = (values["web_mode"] or "http").strip().lower()
        if mode not in {"http", "https"}:
            mode = "http"
        return WebSettingsPayload(
            public_domain=(values["web_public_domain"] or "").strip() or None,
            admin_email=(values["web_admin_email"] or "").strip() or None,
            web_mode=mode,
        )

    def update_web_settings(self, db: Session, payload: WebSettingsPayload) -> WebSettingsPayload:
        payload.public_domain = (payload.public_domain or "").strip() or None
        payload.admin_email = (payload.admin_email or "").strip() or None
        payload.web_mode = (payload.web_mode or "http").strip().lower()
        if payload.web_mode not in {"http", "https"}:
            payload.web_mode = "http"
        mapping = {
            "web_public_domain": payload.public_domain,
            "web_admin_email": payload.admin_email,
            "web_mode": payload.web_mode,
        }
        for key in self.WEB_KEYS:
            setting = self._get_setting(db, key) or AppSetting(key=key, is_encrypted=False)
            value = mapping[key]
            setting.value_text = value
            setting.is_encrypted = False
            db.add(setting)
        db.commit()
        return self.get_web_settings(db)

    def get_raw_backup_marker(self, db: Session, key: str) -> str | None:
        return self._get_value(self._get_setting(db, key))

    def set_raw_backup_marker(self, db: Session, key: str, value: str) -> None:
        setting = self._get_setting(db, key) or AppSetting(key=key, is_encrypted=False)
        setting.value_text = value
        setting.is_encrypted = False
        db.add(setting)
        db.commit()
