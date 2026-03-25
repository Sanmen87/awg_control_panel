from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.backup import BackupJob, BackupStatus
from app.models.job import DeploymentJob, JobStatus, JobType
from app.models.user import User
from app.schemas.backup import BackupJobCreate, BackupJobRead
from app.services.audit import AuditService
from app.services.job_service import JobService

router = APIRouter()


@router.get("", response_model=list[BackupJobRead])
def list_backups(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[BackupJob]:
    return db.query(BackupJob).order_by(BackupJob.created_at.desc()).all()


@router.post("", response_model=BackupJobRead, status_code=status.HTTP_202_ACCEPTED)
def create_backup(
    payload: BackupJobCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BackupJob:
    backup_job = BackupJob(backup_type=payload.backup_type, status=BackupStatus.PENDING)
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
        details=f"Backup requested of type {backup_job.backup_type.value}",
        user_id=current_user.id,
    )
    return backup_job
