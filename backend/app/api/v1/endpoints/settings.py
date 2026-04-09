from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings as app_config
from app.db.session import get_db
from app.models.user import User
from app.schemas.settings import (
    BackupSettingsRead,
    BackupSettingsUpdate,
    DeliverySettingsRead,
    DeliverySettingsUpdate,
    DeliveryTestResult,
    WebSettingsRead,
    WebSettingsUpdate,
    WebStatusRead,
)
from app.services.app_settings import AppSettingsService, BackupSettingsPayload, DeliverySettingsPayload, WebSettingsPayload
from app.services.delivery import DeliveryService
from app.services.web_https import WebHttpsService

router = APIRouter()


@router.get("/delivery", response_model=DeliverySettingsRead)
def get_delivery_settings(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DeliverySettingsRead:
    payload = AppSettingsService().get_delivery_settings(db)
    return DeliverySettingsRead(
        **payload.__dict__,
        smtp_password_configured=bool(payload.smtp_password),
        telegram_bot_token_configured=bool(payload.telegram_bot_token),
    )


@router.patch("/delivery", response_model=DeliverySettingsRead)
def update_delivery_settings(
    update: DeliverySettingsUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DeliverySettingsRead:
    service = AppSettingsService()
    current = service.get_delivery_settings(db)
    payload = DeliverySettingsPayload(
        delivery_email_enabled=update.delivery_email_enabled,
        delivery_telegram_enabled=update.delivery_telegram_enabled,
        admin_email_notifications_enabled=update.admin_email_notifications_enabled,
        admin_telegram_notifications_enabled=update.admin_telegram_notifications_enabled,
        notification_level=update.notification_level,
        smtp_host=(update.smtp_host or "").strip() or None,
        smtp_port=update.smtp_port,
        smtp_username=(update.smtp_username or "").strip() or None,
        smtp_password=update.smtp_password if update.smtp_password is not None else current.smtp_password,
        smtp_from_email=(update.smtp_from_email or "").strip() or None,
        smtp_from_name=(update.smtp_from_name or "").strip() or None,
        smtp_use_tls=update.smtp_use_tls,
        telegram_bot_token=update.telegram_bot_token if update.telegram_bot_token is not None else current.telegram_bot_token,
        telegram_admin_chat_id=(update.telegram_admin_chat_id or "").strip() or None,
        admin_notification_email=(update.admin_notification_email or "").strip() or None,
    )
    updated = service.update_delivery_settings(db, payload)
    return DeliverySettingsRead(
        **updated.__dict__,
        smtp_password_configured=bool(updated.smtp_password),
        telegram_bot_token_configured=bool(updated.telegram_bot_token),
    )


@router.post("/delivery/test-email", response_model=DeliveryTestResult)
def test_email_delivery(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DeliveryTestResult:
    try:
        detail = DeliveryService().send_test_email(db)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DeliveryTestResult(channel="email", status="sent", detail=detail)


@router.post("/delivery/test-telegram", response_model=DeliveryTestResult)
def test_telegram_delivery(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DeliveryTestResult:
    try:
        detail = DeliveryService().send_test_telegram(db)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DeliveryTestResult(channel="telegram", status="sent", detail=detail)


@router.get("/backups", response_model=BackupSettingsRead)
def get_backup_settings(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> BackupSettingsRead:
    payload = AppSettingsService().get_backup_settings(db)
    return BackupSettingsRead(
        **payload.__dict__,
        backup_storage_path=app_config.backup_storage_path,
    )


@router.patch("/backups", response_model=BackupSettingsRead)
def update_backup_settings(
    update: BackupSettingsUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> BackupSettingsRead:
    service = AppSettingsService()
    updated = service.update_backup_settings(
        db,
        BackupSettingsPayload(
            auto_backup_enabled=update.auto_backup_enabled,
            auto_backup_hour_utc=update.auto_backup_hour_utc,
            backup_retention_days=update.backup_retention_days,
        ),
    )
    return BackupSettingsRead(
        **updated.__dict__,
        backup_storage_path=app_config.backup_storage_path,
    )


@router.get("/web", response_model=WebSettingsRead)
def get_web_settings(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> WebSettingsRead:
    payload = AppSettingsService().get_web_settings(db)
    return WebSettingsRead(**WebHttpsService().build_read_payload(payload))


@router.patch("/web", response_model=WebSettingsRead)
def update_web_settings(
    update: WebSettingsUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> WebSettingsRead:
    payload = AppSettingsService().update_web_settings(
        db,
        WebSettingsPayload(
            public_domain=(update.public_domain or "").strip() or None,
            admin_email=(update.admin_email or "").strip() or None,
            web_mode=(update.web_mode or "http").strip().lower(),
        ),
    )
    return WebSettingsRead(**WebHttpsService().build_read_payload(payload))


@router.get("/web/status", response_model=WebStatusRead)
def get_web_status(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> WebStatusRead:
    payload = AppSettingsService().get_web_settings(db)
    return WebHttpsService().get_status(payload)
