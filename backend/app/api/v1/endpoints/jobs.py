from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.job import DeploymentJob, JobStatus, JobType
from app.models.server import Server
from app.models.topology import Topology
from app.models.user import User
from app.schemas.job import DeploymentJobCreate, DeploymentJobRead
from app.services.job_service import JobService

router = APIRouter()


@router.get("", response_model=list[DeploymentJobRead])
def list_jobs(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[DeploymentJob]:
    return db.query(DeploymentJob).order_by(DeploymentJob.created_at.desc()).all()


@router.get("/{job_id}", response_model=DeploymentJobRead)
def get_job(job_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> DeploymentJob:
    job = db.query(DeploymentJob).filter(DeploymentJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.post("", response_model=DeploymentJobRead, status_code=status.HTTP_202_ACCEPTED)
def create_job(
    payload: DeploymentJobCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeploymentJob:
    if payload.server_id and not db.query(Server).filter(Server.id == payload.server_id).first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    if payload.topology_id and not db.query(Topology).filter(Topology.id == payload.topology_id).first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology not found")

    job = DeploymentJob(
        job_type=payload.job_type,
        status=JobStatus.PENDING,
        server_id=payload.server_id,
        topology_id=payload.topology_id,
        requested_by_user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    job.task_id = JobService().dispatch_job(job)
    db.add(job)
    db.commit()
    db.refresh(job)

    return job
