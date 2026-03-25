import json

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.client import Client
from app.models.job import DeploymentJob, JobStatus, JobType
from app.models.server import Server
from app.models.topology import Topology, TopologyStatus, TopologyType
from app.models.topology_node import TopologyNode, TopologyNodeRole
from app.models.user import User
from app.schemas.deploy import TopologyDeployPreview
from app.schemas.job import DeploymentJobRead
from app.schemas.topology import TopologyCreate, TopologyRead, TopologyUpdate
from app.schemas.validation import TopologyValidationResponse
from app.services.audit import AuditService
from app.services.job_service import JobService
from app.services.standard_config_adopter import StandardConfigAdopter
from app.services.topology_validation import TopologyValidationService
from app.services.topology_renderer import RenderedConfig, TopologyRenderError, TopologyRenderer

router = APIRouter()


@router.get("", response_model=list[TopologyRead])
def list_topologies(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[Topology]:
    return db.query(Topology).order_by(Topology.created_at.desc()).all()


@router.post("", response_model=TopologyRead)
def create_topology(
    payload: TopologyCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Topology:
    topology = Topology(**payload.model_dump())
    db.add(topology)
    db.commit()
    db.refresh(topology)
    return topology


@router.delete("/{topology_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_topology(
    topology_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology not found")

    topology_name = topology.name
    db.delete(topology)
    db.commit()
    AuditService().log(
        db,
        action="topology.deleted",
        resource_type="topology",
        resource_id=str(topology_id),
        details=f"Topology {topology_name} deleted",
        user_id=current_user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{topology_id}", response_model=TopologyRead)
def update_topology(
    topology_id: int,
    payload: TopologyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Topology:
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology not found")

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(topology, field, value)

    if "type" in updates:
        topology.status = TopologyStatus.DRAFT

    db.add(topology)
    db.commit()
    db.refresh(topology)
    AuditService().log(
        db,
        action="topology.updated",
        resource_type="topology",
        resource_id=str(topology.id),
        details=f"Topology {topology.name} updated",
        user_id=current_user.id,
    )
    return topology


@router.get("/{topology_id}/validation", response_model=TopologyValidationResponse)
def validate_topology(
    topology_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TopologyValidationResponse:
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology not found")

    nodes = db.query(TopologyNode).filter(TopologyNode.topology_id == topology_id).all()
    result = TopologyValidationService().validate(topology.id, topology.type, nodes)
    return TopologyValidationResponse(
        topology_id=result.topology_id,
        is_valid=result.is_valid,
        errors=result.errors,
        warnings=result.warnings,
    )


@router.get("/{topology_id}/deploy-preview", response_model=TopologyDeployPreview)
def get_deploy_preview(
    topology_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TopologyDeployPreview:
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology not found")

    nodes = db.query(TopologyNode).filter(TopologyNode.topology_id == topology_id).all()
    validation = TopologyValidationService().validate(topology.id, topology.type, nodes)
    if not validation.is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="; ".join(validation.errors))
    servers = db.query(Server).filter(Server.id.in_([node.server_id for node in nodes])).all() if nodes else []
    servers_by_id = {server.id: server for server in servers}
    proxy_node = next((node for node in nodes if node.role == TopologyNodeRole.PROXY), None)
    exit_nodes = [node for node in nodes if node.role == TopologyNodeRole.EXIT]
    standard_node = next((node for node in nodes if node.role == TopologyNodeRole.STANDARD_VPN), None)

    try:
        if topology.type == TopologyType.STANDARD and standard_node:
            standard_server = servers_by_id.get(standard_node.server_id)
            if standard_server and standard_server.config_source == "imported":
                runtime_details: dict[str, object] = {}
                if standard_server.live_runtime_details_json:
                    try:
                        runtime_details = json.loads(standard_server.live_runtime_details_json)
                    except json.JSONDecodeError:
                        runtime_details = {}
                live_config = runtime_details.get("config_preview") or ""
                if not isinstance(live_config, str) or not live_config.strip():
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Imported server config is missing live wg0.conf")
                clients = (
                    db.query(Client)
                    .filter(Client.server_id == standard_server.id, Client.topology_id == topology.id)
                    .order_by(Client.created_at.asc())
                    .all()
                )
                if not clients:
                    clients = (
                        db.query(Client)
                        .filter(Client.server_id == standard_server.id)
                        .order_by(Client.created_at.asc())
                        .all()
                    )
                rendered = [
                    RenderedConfig(
                        server_id=standard_server.id,
                        interface_name=standard_server.live_interface_name or "wg0",
                        remote_path=standard_server.live_config_path or "/opt/amnezia/awg/wg0.conf",
                        content=StandardConfigAdopter().render(standard_server, clients, live_config),
                    )
                ]
            else:
                rendered = TopologyRenderer().render(topology, nodes, servers_by_id)
        else:
            rendered = TopologyRenderer().render(topology, nodes, servers_by_id)
    except TopologyRenderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if topology.type != TopologyType.STANDARD and not proxy_node:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Proxy node is missing")
    if topology.type == TopologyType.STANDARD and not standard_node:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Standard-vpn node is missing")

    return TopologyDeployPreview(
        topology_id=topology.id,
        proxy_server_id=proxy_node.server_id if proxy_node else None,
        exit_server_ids=[node.server_id for node in sorted(exit_nodes, key=lambda item: item.priority)],
        rendered_files={item.remote_path: item.content for item in rendered},
    )


@router.post("/{topology_id}/deploy", response_model=DeploymentJobRead, status_code=status.HTTP_202_ACCEPTED)
def deploy_topology(
    topology_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeploymentJob:
    topology = db.query(Topology).filter(Topology.id == topology_id).first()
    if not topology:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology not found")

    nodes = db.query(TopologyNode).filter(TopologyNode.topology_id == topology_id).all()
    validation = TopologyValidationService().validate(topology.id, topology.type, nodes)
    if not validation.is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="; ".join(validation.errors))

    job = DeploymentJob(
        job_type=JobType.DEPLOY_TOPOLOGY,
        status=JobStatus.PENDING,
        topology_id=topology.id,
        requested_by_user_id=current_user.id,
    )
    topology.status = TopologyStatus.PENDING
    db.add(topology)
    db.add(job)
    db.commit()
    db.refresh(job)
    job.task_id = JobService().dispatch_job(job)
    db.add(job)
    db.commit()
    db.refresh(job)
    AuditService().log(
        db,
        action="topology.deploy.requested",
        resource_type="topology",
        resource_id=str(topology.id),
        details=f"Deployment requested for topology {topology.name}",
        user_id=current_user.id,
    )
    return job
