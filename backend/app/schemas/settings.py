from pydantic import BaseModel


class DeliverySettingsRead(BaseModel):
    delivery_email_enabled: bool
    delivery_telegram_enabled: bool
    admin_email_notifications_enabled: bool
    admin_telegram_notifications_enabled: bool
    notification_level: str
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password_configured: bool = False
    smtp_from_email: str | None = None
    smtp_from_name: str | None = None
    smtp_use_tls: bool = True
    telegram_bot_token_configured: bool = False
    telegram_admin_chat_id: str | None = None
    admin_notification_email: str | None = None


class DeliverySettingsUpdate(BaseModel):
    delivery_email_enabled: bool
    delivery_telegram_enabled: bool
    admin_email_notifications_enabled: bool
    admin_telegram_notifications_enabled: bool
    notification_level: str
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


class DeliveryTestResult(BaseModel):
    channel: str
    status: str
    detail: str


class BackupSettingsRead(BaseModel):
    auto_backup_enabled: bool
    auto_backup_hour_utc: int
    backup_retention_days: int
    backup_storage_path: str


class BackupSettingsUpdate(BaseModel):
    auto_backup_enabled: bool
    auto_backup_hour_utc: int
    backup_retention_days: int


class WebSettingsRead(BaseModel):
    public_domain: str | None = None
    admin_email: str | None = None
    web_mode: str = "http"
    generated_nginx_config: str


class WebSettingsUpdate(BaseModel):
    public_domain: str | None = None
    admin_email: str | None = None
    web_mode: str = "http"


class WebStatusRead(BaseModel):
    public_domain: str | None = None
    web_mode: str = "http"
    dns_ok: bool = False
    resolved_ips: list[str] = []
    port_80_open: bool = False
    port_443_open: bool = False
    certificate_present: bool = False
    certificate_expires_at: str | None = None
    detail: str | None = None
