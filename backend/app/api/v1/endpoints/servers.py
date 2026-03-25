import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.client import Client
from app.models.job import DeploymentJob, JobStatus, JobType
from app.models.server import AWGStatus, AccessStatus, InstallMethod, Server, ServerStatus
from app.models.topology import Topology
from app.models.topology_node import TopologyNode
from app.models.user import User
from app.schemas.job import DeploymentJobRead
from app.schemas.server import ServerBootstrapRequest, ServerCreate, ServerRead, ServerUpdate
from app.services.awg_detection import DETECT_AWG_COMMAND, parse_detection_output
from app.services.audit import AuditService
from app.services.bootstrap_commands import CHECK_SERVER_COMMAND
from app.services.job_service import JobService
from app.services.server_geo import ServerGeoService
from app.services.server_credentials import ServerCredentialsService
from app.services.ssh import SSHService
from app.services.standard_config_inspector import StandardConfigInspector

router = APIRouter()


@router.get("", response_model=list[ServerRead])
def list_servers(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[Server]:
    servers = db.query(Server).order_by(Server.created_at.desc()).all()
    nodes = db.query(TopologyNode).all()
    topologies = {item.id: item for item in db.query(Topology).all()}
    topology_name_by_server: dict[int, str] = {}
    geo = ServerGeoService()
    metadata_changed = False
    for node in nodes:
        topology = topologies.get(node.topology_id)
        if topology and node.server_id not in topology_name_by_server:
            topology_name_by_server[node.server_id] = topology.name
    for server in servers:
        try:
            metadata = json.loads(server.metadata_json) if server.metadata_json else {}
        except json.JSONDecodeError:
            metadata = {}
        if not metadata.get("country_code") or metadata.get("geo_error"):
            next_metadata_json = geo.update_metadata_json(server.metadata_json, server.host)
            if next_metadata_json and next_metadata_json != server.metadata_json:
                server.metadata_json = next_metadata_json
                db.add(server)
                metadata_changed = True
        setattr(server, "topology_name", topology_name_by_server.get(server.id))
    if metadata_changed:
        db.commit()
        for server in servers:
            db.refresh(server)
    return servers


@router.post("", response_model=ServerRead)
def create_server(
    payload: ServerCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Server:
    server_data = payload.model_dump(exclude={"ssh_password", "ssh_private_key", "sudo_password"})
    requested_install_method = server_data.get("install_method")
    if requested_install_method not in {InstallMethod.DOCKER, InstallMethod.GO, InstallMethod.NATIVE}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New server install method must be docker or go")
    if requested_install_method == InstallMethod.NATIVE:
        server_data["install_method"] = InstallMethod.GO
    if not server_data.get("name"):
        server_data["name"] = payload.host
    server = Server(**server_data)
    server.metadata_json = ServerGeoService().update_metadata_json(server.metadata_json, server.host)
    ServerCredentialsService().apply_secrets(
        server,
        ssh_password=payload.ssh_password,
        ssh_private_key=payload.ssh_private_key,
        sudo_password=payload.sudo_password,
    )
    db.add(server)
    db.commit()
    db.refresh(server)
    AuditService().log(
        db,
        action="server.created",
        resource_type="server",
        resource_id=str(server.id),
        details=f"Server {server.name} created with role {server.role.value}",
        user_id=_.id,
    )
    return server


@router.patch("/{server_id}", response_model=ServerRead)
def update_server(
    server_id: int,
    payload: ServerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Server:
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

    server.name = payload.name
    server.description = payload.description
    db.add(server)
    db.commit()
    db.refresh(server)
    AuditService().log(
        db,
        action="server.updated",
        resource_type="server",
        resource_id=str(server.id),
        details=f"Server {server.name} updated",
        user_id=current_user.id,
    )
    return server


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(
    server_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

    topology_node = db.query(TopologyNode).filter(TopologyNode.server_id == server.id).first()
    if topology_node:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Server is attached to a topology and cannot be deleted",
        )

    active_exit_topology = db.query(Topology).filter(Topology.active_exit_server_id == server.id).first()
    if active_exit_topology:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Server is used as an active exit in a topology and cannot be deleted",
        )

    server_name = server.name
    linked_clients = db.query(Client).filter(Client.server_id == server.id, Client.archived.is_(False)).all()
    for client in linked_clients:
        client.archived = True
        client.server_id = None
        client.status = "disabled"
        client.manual_disabled = False
        client.policy_disabled_reason = None
        client.runtime_connected = False
        db.add(client)
    db.delete(server)
    db.commit()
    AuditService().log(
        db,
        action="server.deleted",
        resource_type="server",
        resource_id=str(server_id),
        details=f"Server {server_name} deleted",
        user_id=current_user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{server_id}/check", response_model=DeploymentJobRead, status_code=status.HTTP_202_ACCEPTED)
def check_server(
    server_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeploymentJob:
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

    job = DeploymentJob(
        job_type=JobType.CHECK_SERVER,
        status=JobStatus.PENDING,
        server_id=server.id,
        requested_by_user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    job.task_id = JobService().dispatch_job(job)
    db.add(job)
    db.commit()
    db.refresh(job)
    AuditService().log(
        db,
        action="server.check.requested",
        resource_type="server",
        resource_id=str(server.id),
        details=f"Check requested for {server.name}",
        user_id=current_user.id,
    )
    return job


@router.post("/{server_id}/detect-awg", response_model=DeploymentJobRead, status_code=status.HTTP_202_ACCEPTED)
def detect_awg(
    server_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeploymentJob:
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

    job = DeploymentJob(
        job_type=JobType.DETECT_AWG,
        status=JobStatus.PENDING,
        server_id=server.id,
        requested_by_user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    job.task_id = JobService().dispatch_job(job)
    db.add(job)
    db.commit()
    db.refresh(job)
    AuditService().log(
        db,
        action="server.detect_awg.requested",
        resource_type="server",
        resource_id=str(server.id),
        details=f"AWG detection requested for {server.name}",
        user_id=current_user.id,
    )
    return job


@router.post("/{server_id}/bootstrap", response_model=DeploymentJobRead, status_code=status.HTTP_202_ACCEPTED)
def bootstrap_server(
    server_id: int,
    payload: ServerBootstrapRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeploymentJob:
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

    requested_install_method = payload.install_method if payload else None
    if requested_install_method is not None:
        if requested_install_method not in {InstallMethod.DOCKER, InstallMethod.GO, InstallMethod.NATIVE}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bootstrap install method must be docker or go")
        server.install_method = InstallMethod.GO if requested_install_method == InstallMethod.NATIVE else requested_install_method
        db.add(server)
        db.commit()
        db.refresh(server)

    job = DeploymentJob(
        job_type=JobType.BOOTSTRAP_SERVER,
        status=JobStatus.PENDING,
        server_id=server.id,
        requested_by_user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    job.task_id = JobService().dispatch_job(job)
    db.add(job)
    db.commit()
    db.refresh(job)
    AuditService().log(
        db,
        action="server.bootstrap.requested",
        resource_type="server",
        resource_id=str(server.id),
        details=f"Bootstrap requested for {server.name}",
        user_id=current_user.id,
    )
    return job


@router.post("/{server_id}/inspect-standard", response_model=ServerRead)
def inspect_standard_server(
    server_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Server:
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    if server.access_status.value != "ok":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Server access check must succeed first")
    if not server.awg_detected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="AWG must be detected before importing live config")

    inspection = asyncio.run(StandardConfigInspector().inspect(server))
    server.config_source = "imported" if inspection.interface or inspection.listen_port or inspection.peer_count else "generated"
    server.live_interface_name = inspection.interface
    server.live_config_path = inspection.config_path or (
        f"docker://{inspection.docker_container}" if inspection.docker_container else None
    )
    server.live_address_cidr = inspection.address_cidr
    server.live_listen_port = inspection.listen_port
    server.live_peer_count = inspection.peer_count
    server.live_runtime_details_json = inspection.raw_json
    try:
        details = __import__("json").loads(inspection.raw_json)
        clients_table_preview = str(details.get("clients_table_preview") or "").strip()
        peers = details.get("peers") or []
        if clients_table_preview:
            preview_head = clients_table_preview[:220].replace("\n", " | ")
            server.last_error = (
                f"DEBUG clientsTable found; len={len(clients_table_preview)}; "
                f"peers={len(peers)}; preview={preview_head}"
            )
        else:
            server.last_error = "DEBUG clientsTable not found or empty"
    except Exception:
        server.last_error = "DEBUG clientsTable parse failed"
    db.add(server)
    db.commit()
    db.refresh(server)
    AuditService().log(
        db,
        action="server.inspect_standard.completed",
        resource_type="server",
        resource_id=str(server.id),
        details=f"Imported live standard config summary for {server.name}",
        user_id=current_user.id,
    )
    return server


@router.post("/{server_id}/prepare", response_model=ServerRead)
def prepare_server(
    server_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Server:
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

    creds = ServerCredentialsService()
    ssh = SSHService()

    try:
        check_result = asyncio.run(
            ssh.run_command(
                host=server.host,
                username=server.ssh_user,
                port=server.ssh_port,
                password=creds.get_ssh_password(server),
                private_key=creds.get_private_key(server),
                command=CHECK_SERVER_COMMAND,
            )
        )
        if check_result.exit_status != 0:
            message = check_result.stderr.strip() or check_result.stdout.strip() or "Server check failed"
            server.status = ServerStatus.ERROR
            server.access_status = AccessStatus.FAILED
            server.awg_status = AWGStatus.UNKNOWN
            server.ready_for_topology = False
            server.last_error = message
            db.add(server)
            db.commit()
            db.refresh(server)
            return server

        check_payload = json.loads(check_result.stdout.strip().splitlines()[-1])
        server.status = ServerStatus.HEALTHY
        server.access_status = AccessStatus.OK
        server.os_name = check_payload.get("os_name") or server.os_name
        server.os_version = check_payload.get("os_version") or server.os_version
        server.metadata_json = ServerGeoService().update_metadata_json(server.metadata_json, server.host)
        server.last_error = None

        detect_result = asyncio.run(
            ssh.run_command(
                host=server.host,
                username=server.ssh_user,
                port=server.ssh_port,
                password=creds.get_ssh_password(server),
                private_key=creds.get_private_key(server),
                command=DETECT_AWG_COMMAND,
            )
        )
        if detect_result.exit_status != 0:
            raise RuntimeError(detect_result.stderr.strip() or detect_result.stdout.strip() or "AWG detection failed")

        parsed = parse_detection_output(detect_result.stdout)
        server.awg_detected = parsed.detected
        server.awg_version = parsed.version
        server.os_name = parsed.os_name or server.os_name
        server.os_version = parsed.os_version or server.os_version
        server.install_method = InstallMethod(parsed.install_type)
        server.runtime_flavor = parsed.runtime_flavor
        server.awg_interfaces_json = parsed.interfaces_json
        server.awg_status = AWGStatus.DETECTED if parsed.detected else AWGStatus.MISSING
        server.status = ServerStatus.HEALTHY if parsed.detected else ServerStatus.DEGRADED
        server.ready_for_topology = parsed.detected

        if parsed.detected:
            try:
                inspection = asyncio.run(StandardConfigInspector().inspect(server))
                server.config_source = "imported" if inspection.interface or inspection.listen_port or inspection.peer_count else "generated"
                server.live_interface_name = inspection.interface
                server.live_config_path = inspection.config_path or (
                    f"docker://{inspection.docker_container}" if inspection.docker_container else None
                )
                server.live_address_cidr = inspection.address_cidr
                server.live_listen_port = inspection.listen_port
                server.live_peer_count = inspection.peer_count
                server.live_runtime_details_json = inspection.raw_json
                server.last_error = None
            except Exception as exc:  # noqa: BLE001
                server.last_error = f"Live config import failed: {exc}"
        else:
            server.config_source = "generated"
            server.live_interface_name = None
            server.live_config_path = None
            server.live_address_cidr = None
            server.live_listen_port = None
            server.live_peer_count = None
            server.live_runtime_details_json = None
            server.last_error = "AWG runtime not detected"

        db.add(server)
        db.commit()
        db.refresh(server)
        AuditService().log(
            db,
            action="server.prepared",
            resource_type="server",
            resource_id=str(server.id),
            details=f"Prepare pipeline completed for {server.name}",
            user_id=current_user.id,
        )
        return server
    except Exception as exc:  # noqa: BLE001
        server.status = ServerStatus.ERROR
        server.access_status = AccessStatus.FAILED if server.access_status != AccessStatus.OK else server.access_status
        server.ready_for_topology = False
        server.last_error = str(exc)
        db.add(server)
        db.commit()
        db.refresh(server)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
