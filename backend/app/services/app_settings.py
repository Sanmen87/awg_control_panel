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
