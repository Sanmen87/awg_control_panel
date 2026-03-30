import json
from pathlib import Path
import re
import shutil
import tarfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.backup import BackupJob, BackupStatus, BackupType
from app.models.job import DeploymentJob, JobStatus, JobType
from app.models.server import Server
from app.models.user import User
from app.schemas.backup import BackupJobCreate, BackupJobRead, BackupPreviewRead, BackupPreviewServerRead, BackupRestoreRequest
from app.schemas.job import DeploymentJobRead
from app.services.audit import AuditService
from app.services.job_service import JobService

router = APIRouter()


def _slugify_backup_part(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    normalized = normalized.strip("-._")
    return normalized or fallback


def _backup_manifest_summary(backup_job: BackupJob) -> dict[str, str | None]:
    if not backup_job.storage_path:
        return {
            "manifest_server_name": None,
            "manifest_server_host": None,
            "manifest_install_method": None,
        }
    archive_path = Path(backup_job.storage_path)
    if not archive_path.exists():
        return {
            "manifest_server_name": None,
            "manifest_server_host": None,
            "manifest_install_method": None,
        }
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            member = archive.getmember("manifest.json")
            manifest = json.loads(archive.extractfile(member).read().decode("utf-8"))
    except Exception:
        return {
            "manifest_server_name": None,
            "manifest_server_host": None,
            "manifest_install_method": None,
        }
    if not isinstance(manifest, dict):
        return {
            "manifest_server_name": None,
            "manifest_server_host": None,
            "manifest_install_method": None,
        }
    server_payload = manifest.get("server")
    if not isinstance(server_payload, dict):
        panel_payload = manifest.get("panel")
        if isinstance(panel_payload, dict):
            return {
                "manifest_server_name": panel_payload.get("project_name") if isinstance(panel_payload.get("project_name"), str) else None,
                "manifest_server_host": None,
                "manifest_install_method": "database",
            }
        return {
            "manifest_server_name": None,
            "manifest_server_host": None,
            "manifest_install_method": None,
        }
    return {
        "manifest_server_name": server_payload.get("name") if isinstance(server_payload.get("name"), str) else None,
        "manifest_server_host": server_payload.get("host") if isinstance(server_payload.get("host"), str) else None,
        "manifest_install_method": server_payload.get("install_method") if isinstance(server_payload.get("install_method"), str) else None,
    }


def _serialize_backup_job(backup_job: BackupJob) -> BackupJobRead:
    summary = _backup_manifest_summary(backup_job)
    return BackupJobRead(
        id=backup_job.id,
        backup_type=backup_job.backup_type,
        server_id=backup_job.server_id,
        status=backup_job.status,
        storage_path=backup_job.storage_path,
        result_message=backup_job.result_message,
        manifest_server_name=summary["manifest_server_name"],
        manifest_server_host=summary["manifest_server_host"],
        manifest_install_method=summary["manifest_install_method"],
        created_at=backup_job.created_at,
        updated_at=backup_job.updated_at,
    )


def _read_backup_manifest(backup_job: BackupJob) -> dict[str, object]:
    if not backup_job.storage_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Backup archive is not ready")
    archive_path = Path(backup_job.storage_path)
    if not archive_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup archive file not found")
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            member = archive.getmember("manifest.json")
            manifest = json.loads(archive.extractfile(member).read().decode("utf-8"))
            has_panel_dump = any(item.name == "panel/postgres.sql" for item in archive.getmembers())
            if not isinstance(manifest, dict):
                raise ValueError("invalid manifest")
            manifest["_has_panel_dump"] = has_panel_dump
            return manifest
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Backup manifest read failed: {exc}") from exc


def _preview_from_manifest(manifest: dict[str, object]) -> BackupPreviewRead:
    servers: list[BackupPreviewServerRead] = []
    raw_servers = manifest.get("servers")
    if isinstance(raw_servers, list):
        for item in raw_servers:
            if not isinstance(item, dict):
                continue
            server_id = item.get("id") if isinstance(item.get("id"), int) else item.get("server_id")
            if not isinstance(server_id, int):
                continue
            servers.append(
                BackupPreviewServerRead(
                    server_id=server_id,
                    name=item.get("name") if isinstance(item.get("name"), str) else None,
                    host=item.get("host") if isinstance(item.get("host"), str) else None,
                    install_method=item.get("install_method") if isinstance(item.get("install_method"), str) else None,
                    runtime_flavor=item.get("runtime_flavor") if isinstance(item.get("runtime_flavor"), str) else None,
                    live_interface_name=item.get("live_interface_name") if isinstance(item.get("live_interface_name"), str) else None,
                    live_config_path=item.get("live_config_path") if isinstance(item.get("live_config_path"), str) else None,
                    clients_table_path=item.get("clients_table_path") if isinstance(item.get("clients_table_path"), str) else None,
                    has_clients_table=bool(item.get("clients_table_path")),
                )
            )
    server_payload = manifest.get("server")
    if isinstance(server_payload, dict):
        server_id = server_payload.get("id")
        if isinstance(server_id, int):
            servers.append(
                BackupPreviewServerRead(
                    server_id=server_id,
                    name=server_payload.get("name") if isinstance(server_payload.get("name"), str) else None,
                    host=server_payload.get("host") if isinstance(server_payload.get("host"), str) else None,
                    install_method=server_payload.get("install_method") if isinstance(server_payload.get("install_method"), str) else None,
                    runtime_flavor=server_payload.get("runtime_flavor") if isinstance(server_payload.get("runtime_flavor"), str) else None,
                    live_interface_name=server_payload.get("live_interface_name") if isinstance(server_payload.get("live_interface_name"), str) else None,
                    live_config_path=server_payload.get("live_config_path") if isinstance(server_payload.get("live_config_path"), str) else None,
                    clients_table_path=None,
                    has_clients_table=False,
                )
            )
    panel_payload = manifest.get("panel")
    return BackupPreviewRead(
        backup_type=manifest.get("backup_type") if isinstance(manifest.get("backup_type"), str) else "unknown",
        created_at=manifest.get("created_at") if isinstance(manifest.get("created_at"), str) else None,
        panel_project_name=panel_payload.get("project_name") if isinstance(panel_payload, dict) and isinstance(panel_payload.get("project_name"), str) else None,
        has_panel_dump=bool(manifest.get("_has_panel_dump")),
        servers=servers,
    )


def _read_manifest_from_archive_path(archive_path: Path) -> dict[str, object]:
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            member = archive.getmember("manifest.json")
            manifest = json.loads(archive.extractfile(member).read().decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Backup manifest read failed: {exc}") from exc
    if not isinstance(manifest, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Backup manifest is invalid")
    return manifest


def _download_filename(backup_job: BackupJob) -> str:
    summary = _backup_manifest_summary(backup_job)
    archive_suffix = Path(backup_job.storage_path or "").name
    if archive_suffix.endswith(".tar.gz"):
        archive_suffix = archive_suffix[:-7]
    server_name = _slugify_backup_part(summary["manifest_server_name"], f"server-{backup_job.server_id or backup_job.id}")
    server_host = _slugify_backup_part(summary["manifest_server_host"], "unknown-host")
    timestamp = backup_job.created_at.strftime("%Y%m%dT%H%M%SZ")
    return f"{server_name}-{server_host}-backup-{backup_job.id}-{timestamp}.tar.gz"


@router.get("", response_model=list[BackupJobRead])
def list_backups(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[BackupJobRead]:
    return [_serialize_backup_job(item) for item in db.query(BackupJob).order_by(BackupJob.created_at.desc()).all()]


@router.delete("/{backup_job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_backup(
    backup_job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    backup_job = db.query(BackupJob).filter(BackupJob.id == backup_job_id).first()
    if not backup_job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")

    storage_path = Path(backup_job.storage_path) if backup_job.storage_path else None
    if storage_path and storage_path.exists():
        try:
            storage_path.unlink()
        except Exception:
            pass

    db.delete(backup_job)
    db.commit()

    AuditService().log(
        db,
        action="backup.deleted",
        resource_type="backup",
        resource_id=str(backup_job_id),
        details=f"Backup #{backup_job_id} deleted from panel",
        user_id=current_user.id,
    )


@router.get("/{backup_job_id}/preview", response_model=BackupPreviewRead)
def preview_backup(
    backup_job_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> BackupPreviewRead:
    backup_job = db.query(BackupJob).filter(BackupJob.id == backup_job_id).first()
    if not backup_job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")
    manifest = _read_backup_manifest(backup_job)
    return _preview_from_manifest(manifest)


@router.get("/{backup_job_id}/download")
def download_backup(
    backup_job_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> FileResponse:
    backup_job = db.query(BackupJob).filter(BackupJob.id == backup_job_id).first()
    if not backup_job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")
    if backup_job.status != BackupStatus.SUCCEEDED or not backup_job.storage_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Backup archive is not ready")
    archive_path = Path(backup_job.storage_path)
    if not archive_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup archive file not found")
    return FileResponse(path=archive_path, filename=_download_filename(backup_job), media_type="application/gzip")


@router.post("", response_model=BackupJobRead, status_code=status.HTTP_202_ACCEPTED)
def create_backup(
    payload: BackupJobCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BackupJob:
    if payload.backup_type.value == "server":
        if not payload.server_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="server_id is required for server backups")
        server = db.query(Server).filter(Server.id == payload.server_id).first()
        if not server:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

    backup_job = BackupJob(
        backup_type=payload.backup_type,
        server_id=payload.server_id,
        status=BackupStatus.PENDING,
    )
    db.add(backup_job)
    db.commit()
    db.refresh(backup_job)

    deployment_job = DeploymentJob(
        job_type=JobType.BACKUP,
        status=JobStatus.PENDING,
        requested_by_user_id=current_user.id,
        result_message=f"BackupJob:{backup_job.id}",
    )
    db.add(deployment_job)
    db.commit()
    db.refresh(deployment_job)
    deployment_job.task_id = JobService().dispatch_job(deployment_job)
    db.add(deployment_job)
    db.commit()

    AuditService().log(
        db,
        action="backup.requested",
        resource_type="backup",
        resource_id=str(backup_job.id),
        details=f"Backup requested of type {backup_job.backup_type.value}"
        + (f" for server #{backup_job.server_id}" if backup_job.server_id else ""),
        user_id=current_user.id,
    )
    return _serialize_backup_job(backup_job)


@router.post("/upload", response_model=BackupJobRead, status_code=status.HTTP_201_CREATED)
async def upload_backup(
    backup_type: str = Form(...),
    server_id: int | None = Form(default=None),
    archive: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BackupJob:
    if server_id and not db.query(Server).filter(Server.id == server_id).first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

    backup_dir = Path(settings.backup_storage_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(archive.filename or "uploaded-server-backup.tar.gz").name
    storage_path = backup_dir / f"uploaded-{safe_name}"
    with storage_path.open("wb") as fh:
        shutil.copyfileobj(archive.file, fh)
    manifest = _read_manifest_from_archive_path(storage_path)
    manifest_backup_type = manifest.get("backup_type") if isinstance(manifest.get("backup_type"), str) else None
    if manifest_backup_type not in {"server", "database", "full"}:
        try:
            storage_path.unlink()
        except Exception:
            pass
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported backup type in manifest")

    backup_job = BackupJob(
        backup_type=BackupType(manifest_backup_type),
        server_id=server_id,
        status=BackupStatus.SUCCEEDED,
        storage_path=str(storage_path),
        result_message=f"Uploaded backup archive ({manifest_backup_type})",
    )
    db.add(backup_job)
    db.commit()
    db.refresh(backup_job)

    AuditService().log(
        db,
        action="backup.uploaded",
        resource_type="backup",
        resource_id=str(backup_job.id),
        details=f"Uploaded server backup archive {storage_path.name}",
        user_id=current_user.id,
    )
    return _serialize_backup_job(backup_job)


@router.post("/{backup_job_id}/restore", response_model=DeploymentJobRead, status_code=status.HTTP_202_ACCEPTED)
def restore_backup(
    backup_job_id: int,
    payload: BackupRestoreRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeploymentJob:
    backup_job = db.query(BackupJob).filter(BackupJob.id == backup_job_id).first()
    if not backup_job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")
    if backup_job.backup_type.value not in {"server", "database", "full"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported backup type for restore")
    if backup_job.status != BackupStatus.SUCCEEDED or not backup_job.storage_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Backup archive is not ready for restore")

    target_server = None
    if backup_job.backup_type.value == "server":
        target_server_id = payload.server_id or backup_job.server_id
        if not target_server_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="server_id is required for restore")
        target_server = db.query(Server).filter(Server.id == target_server_id).first()
        if not target_server:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target server not found")
        deployment_job = DeploymentJob(
            job_type=JobType.RESTORE_SERVER,
            status=JobStatus.PENDING,
            server_id=target_server.id,
            requested_by_user_id=current_user.id,
            result_message=f"RestoreBackupJob:{backup_job.id}",
        )
    elif backup_job.backup_type.value == "full":
        if payload.server_id:
            if not payload.bundle_server_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="bundle_server_id is required for full bundle server restore")
            target_server = db.query(Server).filter(Server.id == payload.server_id).first()
            if not target_server:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target server not found")
            deployment_job = DeploymentJob(
                job_type=JobType.RESTORE_SERVER,
                status=JobStatus.PENDING,
                server_id=target_server.id,
                requested_by_user_id=current_user.id,
                result_message=f"RestoreBackupJob:{backup_job.id}:{payload.bundle_server_id}",
            )
        else:
            deployment_job = DeploymentJob(
                job_type=JobType.RESTORE_PANEL,
                status=JobStatus.PENDING,
                requested_by_user_id=current_user.id,
                result_message=f"RestoreBackupJob:{backup_job.id}",
            )
    else:
        deployment_job = DeploymentJob(
            job_type=JobType.RESTORE_PANEL,
            status=JobStatus.PENDING,
            requested_by_user_id=current_user.id,
            result_message=f"RestoreBackupJob:{backup_job.id}",
        )
    db.add(deployment_job)
    db.commit()
    db.refresh(deployment_job)

    deployment_job.task_id = JobService().dispatch_job(deployment_job)
    db.add(deployment_job)
    db.commit()
    db.refresh(deployment_job)

    AuditService().log(
        db,
        action="backup.restore_requested",
        resource_type="backup",
        resource_id=str(backup_job.id),
        details=(
            f"Restore requested from backup #{backup_job.id} to server #{target_server.id}"
            if target_server
            else f"Panel restore requested from backup #{backup_job.id}"
        ),
        user_id=current_user.id,
    )
    return deployment_job
