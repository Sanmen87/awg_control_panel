import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.job import DeploymentJob, JobStatus, JobType
from app.models.server import Server
from app.models.service_instance import ServiceInstance
from app.models.topology import Topology, TopologyType
from app.models.topology_node import TopologyNode, TopologyNodeRole
from app.models.user import User
from app.schemas.extra_service import EligibleServiceServerRead, ExtraServiceCreate, ExtraServiceDeliveryRequest, ExtraServiceRead
from app.services.audit import AuditService
from app.services.bootstrap_commands import wrap_with_optional_sudo
from app.services.delivery import DeliveryService
from app.services.job_service import JobService
from app.services.server_credentials import ServerCredentialsService
from app.services.ssh import SSHService

router = APIRouter()


def _validate_mtproxy_script_domain(raw_domain: str) -> str:
    domain = raw_domain.strip().lower()
    if not domain:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fake TLS domain is required")
    if len(domain.encode("utf-8").hex()) > 30:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fake TLS domain is too long for script-mode secret. Use a shorter domain like vk.com or ya.ru.",
        )
    return domain


def _validate_xray_domain(raw_domain: str) -> str:
    domain = raw_domain.strip().lower()
    if not domain:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reality server name is required")
    if len(domain) > 255:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reality server name is too long")
    return domain


def _parse_service_id_from_job(job: DeploymentJob) -> int | None:
    if job.job_type != JobType.INSTALL_EXTRA_SERVICE or not job.result_message:
        return None
    if not job.result_message.startswith("ExtraService:"):
        return None
    raw_tail = job.result_message.split(":", maxsplit=1)[1]
    raw_id = raw_tail.split("|", maxsplit=1)[0].strip()
    if not raw_id.isdigit():
        return None
    return int(raw_id)


def _server_has_named_service(server: Server, service_type: str) -> bool:
    creds = ServerCredentialsService()
    if service_type == "mtproxy":
        container_pattern = "^awg-mtproxy-[0-9]+$"
        remote_glob = "/opt/awg-extra-services/mtproxy-*"
        service_name = "MTProxy"
    elif service_type == "socks5":
        container_pattern = "^awg-socks5-[0-9]+$"
        remote_glob = "/opt/awg-extra-services/socks5-*"
        service_name = "SOCKS5"
    else:
        container_pattern = "^awg-xray-[0-9]+$"
        remote_glob = "/opt/awg-extra-services/xray-*"
        service_name = "Xray"
    command = wrap_with_optional_sudo(
        f"""
set -e
if command -v docker >/dev/null 2>&1; then
  if docker ps -a --format '{{{{.Names}}}}' | grep -E '{container_pattern}' >/dev/null 2>&1; then
    echo FOUND
    exit 0
  fi
fi
if ls -d {remote_glob} >/dev/null 2>&1; then
  echo FOUND
  exit 0
fi
echo MISSING
""".strip(),
        creds.get_sudo_password(server),
    )
    result = asyncio.run(
        SSHService().run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=creds.get_ssh_password(server),
            private_key=creds.get_private_key(server),
            command=command,
            timeout_seconds=120,
        )
    )
    if result.exit_status != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Unable to inspect server for {service_name}")
    return result.stdout.strip() == "FOUND"


def _service_config(item: ServiceInstance) -> dict[str, object]:
    if not item.config_json:
        return {}
    try:
        loaded = json.loads(item.config_json)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _service_runtime(item: ServiceInstance) -> dict[str, object]:
    if not item.runtime_details_json:
        return {}
    try:
        loaded = json.loads(item.runtime_details_json)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _refresh_mtproxy_service(db: Session, item: ServiceInstance, server: Server) -> None:
    creds = ServerCredentialsService()
    config = _service_config(item)
    runtime = _service_runtime(item)
    container_name = str(runtime.get("container_name") or config.get("container_name") or f"awg-mtproxy-{item.id}")
    remote_dir = str(runtime.get("remote_dir") or config.get("remote_dir") or f"/opt/awg-extra-services/mtproxy-{item.id}")
    command = wrap_with_optional_sudo(
        f"""
set -e
if ! command -v docker >/dev/null 2>&1; then
  echo status=missing
  exit 0
fi
container_status="$(docker inspect -f '{{{{.State.Status}}}}' {container_name} 2>/dev/null || true)"
if [ -z "${{container_status:-}}" ]; then
  echo status=missing
  exit 0
fi
echo status="$container_status"
""".strip(),
        creds.get_sudo_password(server),
    )
    result = asyncio.run(
        SSHService().run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=creds.get_ssh_password(server),
            private_key=creds.get_private_key(server),
            command=command,
            timeout_seconds=120,
        )
    )
    if result.exit_status != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Unable to inspect MTProxy container")
    remote_status = "unknown"
    for line in result.stdout.splitlines():
        if line.startswith("status="):
            remote_status = line.split("=", maxsplit=1)[1].strip()
            break
    runtime.update(
        {
            "container_name": container_name,
            "remote_dir": remote_dir,
            "container_status": remote_status,
        }
    )
    config["container_name"] = container_name
    config["remote_dir"] = remote_dir
    if remote_status == "running":
        item.status = "running"
        config["install_state"] = "installed"
        item.last_error = None
    elif remote_status in {"created", "restarting", "paused"}:
        item.status = "installing"
        config["install_state"] = "installing"
    elif remote_status in {"exited", "dead", "missing"}:
        item.status = "error"
        config["install_state"] = "error"
        item.last_error = f"MTProxy container state: {remote_status}"
    else:
        item.status = remote_status
    item.config_json = json.dumps(config)
    item.runtime_details_json = json.dumps(runtime)
    db.add(item)


def _refresh_socks5_service(db: Session, item: ServiceInstance, server: Server) -> None:
    creds = ServerCredentialsService()
    config = _service_config(item)
    runtime = _service_runtime(item)
    container_name = str(runtime.get("container_name") or config.get("container_name") or f"awg-socks5-{item.id}")
    remote_dir = str(runtime.get("remote_dir") or config.get("remote_dir") or f"/opt/awg-extra-services/socks5-{item.id}")
    command = wrap_with_optional_sudo(
        f"""
set -e
if ! command -v docker >/dev/null 2>&1; then
  echo status=missing
  exit 0
fi
container_status="$(docker inspect -f '{{{{.State.Status}}}}' {container_name} 2>/dev/null || true)"
if [ -z "${{container_status:-}}" ]; then
  echo status=missing
  exit 0
fi
echo status="$container_status"
""".strip(),
        creds.get_sudo_password(server),
    )
    result = asyncio.run(
        SSHService().run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=creds.get_ssh_password(server),
            private_key=creds.get_private_key(server),
            command=command,
            timeout_seconds=120,
        )
    )
    if result.exit_status != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Unable to inspect SOCKS5 container")
    remote_status = "unknown"
    for line in result.stdout.splitlines():
        if line.startswith("status="):
            remote_status = line.split("=", maxsplit=1)[1].strip()
            break
    runtime.update(
        {
            "container_name": container_name,
            "remote_dir": remote_dir,
            "container_status": remote_status,
        }
    )
    config["container_name"] = container_name
    config["remote_dir"] = remote_dir
    if remote_status == "running":
        item.status = "running"
        config["install_state"] = "installed"
        item.last_error = None
    elif remote_status in {"created", "restarting", "paused"}:
        item.status = "installing"
        config["install_state"] = "installing"
    elif remote_status in {"exited", "dead", "missing"}:
        item.status = "error"
        config["install_state"] = "error"
        item.last_error = f"SOCKS5 container state: {remote_status}"
    else:
        item.status = remote_status
    item.config_json = json.dumps(config)
    item.runtime_details_json = json.dumps(runtime)
    db.add(item)


def _delete_mtproxy_from_server(item: ServiceInstance, server: Server) -> None:
    creds = ServerCredentialsService()
    config = _service_config(item)
    runtime = _service_runtime(item)
    container_name = str(runtime.get("container_name") or config.get("container_name") or f"awg-mtproxy-{item.id}")
    remote_dir = str(runtime.get("remote_dir") or config.get("remote_dir") or f"/opt/awg-extra-services/mtproxy-{item.id}")
    command = wrap_with_optional_sudo(
        f"""
set -e
if command -v docker >/dev/null 2>&1; then
  docker rm -f {container_name} >/dev/null 2>&1 || true
fi
rm -rf {remote_dir}
""".strip(),
        creds.get_sudo_password(server),
    )
    result = asyncio.run(
        SSHService().run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=creds.get_ssh_password(server),
            private_key=creds.get_private_key(server),
            command=command,
            timeout_seconds=300,
        )
    )
    if result.exit_status != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Unable to remove MTProxy from server")


def _delete_socks5_from_server(item: ServiceInstance, server: Server) -> None:
    creds = ServerCredentialsService()
    config = _service_config(item)
    runtime = _service_runtime(item)
    container_name = str(runtime.get("container_name") or config.get("container_name") or f"awg-socks5-{item.id}")
    remote_dir = str(runtime.get("remote_dir") or config.get("remote_dir") or f"/opt/awg-extra-services/socks5-{item.id}")
    command = wrap_with_optional_sudo(
        f"""
set -e
if command -v docker >/dev/null 2>&1; then
  docker rm -f {container_name} >/dev/null 2>&1 || true
fi
rm -rf {remote_dir}
""".strip(),
        creds.get_sudo_password(server),
    )
    result = asyncio.run(
        SSHService().run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=creds.get_ssh_password(server),
            private_key=creds.get_private_key(server),
            command=command,
            timeout_seconds=300,
        )
    )
    if result.exit_status != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Unable to remove SOCKS5 from server")


def _refresh_xray_service(db: Session, item: ServiceInstance, server: Server) -> None:
    creds = ServerCredentialsService()
    config = _service_config(item)
    runtime = _service_runtime(item)
    container_name = str(runtime.get("container_name") or config.get("container_name") or f"awg-xray-{item.id}")
    remote_dir = str(runtime.get("remote_dir") or config.get("remote_dir") or f"/opt/awg-extra-services/xray-{item.id}")
    command = wrap_with_optional_sudo(
        f"""
set -e
if ! command -v docker >/dev/null 2>&1; then
  echo status=missing
  exit 0
fi
container_status="$(docker inspect -f '{{{{.State.Status}}}}' {container_name} 2>/dev/null || true)"
if [ -z "${{container_status:-}}" ]; then
  echo status=missing
  exit 0
fi
echo status="$container_status"
""".strip(),
        creds.get_sudo_password(server),
    )
    result = asyncio.run(
        SSHService().run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=creds.get_ssh_password(server),
            private_key=creds.get_private_key(server),
            command=command,
            timeout_seconds=120,
        )
    )
    if result.exit_status != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Unable to inspect Xray container")
    remote_status = "unknown"
    for line in result.stdout.splitlines():
        if line.startswith("status="):
            remote_status = line.split("=", maxsplit=1)[1].strip()
            break
    runtime.update(
        {
            "container_name": container_name,
            "remote_dir": remote_dir,
            "container_status": remote_status,
        }
    )
    config["container_name"] = container_name
    config["remote_dir"] = remote_dir
    if remote_status == "running":
        item.status = "running"
        config["install_state"] = "installed"
        item.last_error = None
    elif remote_status in {"created", "restarting", "paused"}:
        item.status = "installing"
        config["install_state"] = "installing"
    elif remote_status in {"exited", "dead", "missing"}:
        item.status = "error"
        config["install_state"] = "error"
        item.last_error = f"Xray container state: {remote_status}"
    else:
        item.status = remote_status
    item.config_json = json.dumps(config)
    item.runtime_details_json = json.dumps(runtime)
    db.add(item)


def _delete_xray_from_server(item: ServiceInstance, server: Server) -> None:
    creds = ServerCredentialsService()
    config = _service_config(item)
    runtime = _service_runtime(item)
    container_name = str(runtime.get("container_name") or config.get("container_name") or f"awg-xray-{item.id}")
    remote_dir = str(runtime.get("remote_dir") or config.get("remote_dir") or f"/opt/awg-extra-services/xray-{item.id}")
    command = wrap_with_optional_sudo(
        f"""
set -e
if command -v docker >/dev/null 2>&1; then
  docker rm -f {container_name} >/dev/null 2>&1 || true
fi
rm -rf {remote_dir}
""".strip(),
        creds.get_sudo_password(server),
    )
    result = asyncio.run(
        SSHService().run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=creds.get_ssh_password(server),
            private_key=creds.get_private_key(server),
            command=command,
            timeout_seconds=300,
        )
    )
    if result.exit_status != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Unable to remove Xray from server")


def _eligible_servers(
    db: Session,
) -> list[tuple[Server, Topology | None, TopologyNodeRole | None]]:
    servers = db.query(Server).order_by(Server.name.asc()).all()
    nodes = db.query(TopologyNode).all()
    topologies = {item.id: item for item in db.query(Topology).all()}
    node_by_server_id = {node.server_id: node for node in nodes}
    eligible: list[tuple[Server, Topology | None, TopologyNodeRole | None]] = []
    for server in servers:
        node = node_by_server_id.get(server.id)
        topology = topologies.get(node.topology_id) if node else None
        if topology and topology.type in {TopologyType.PROXY_EXIT, TopologyType.PROXY_MULTI_EXIT}:
            if node and node.role == TopologyNodeRole.EXIT:
                eligible.append((server, topology, node.role))
            continue
        eligible.append((server, topology, node.role if node else None))
    return eligible


def _hydrate_service_read(
    item: ServiceInstance,
    server_by_id: dict[int, Server],
    node_by_server_id: dict[int, TopologyNode],
    topology_by_id: dict[int, Topology],
    install_jobs_by_service_id: dict[int, DeploymentJob],
) -> ExtraServiceRead:
    server = server_by_id.get(item.server_id)
    node = node_by_server_id.get(item.server_id)
    topology = topology_by_id.get(node.topology_id) if node else None
    install_job = install_jobs_by_service_id.get(item.id)
    return ExtraServiceRead(
        id=item.id,
        service_type=item.service_type,
        server_id=item.server_id,
        server_name=server.name if server else None,
        server_host=server.host if server else None,
        topology_name=topology.name if topology else None,
        topology_role=node.role.value if node else None,
        status=item.status,
        config_json=item.config_json,
        runtime_details_json=item.runtime_details_json,
        public_endpoint=item.public_endpoint,
        last_error=item.last_error,
        install_job_id=install_job.id if install_job else None,
        install_job_status=install_job.status.value if install_job else None,
        install_job_task_id=install_job.task_id if install_job else None,
        install_job_updated_at=install_job.updated_at if install_job else None,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _latest_install_jobs_by_service_id(db: Session) -> dict[int, DeploymentJob]:
    jobs = (
        db.query(DeploymentJob)
        .filter(DeploymentJob.job_type == JobType.INSTALL_EXTRA_SERVICE)
        .order_by(DeploymentJob.updated_at.desc(), DeploymentJob.id.desc())
        .all()
    )
    latest: dict[int, DeploymentJob] = {}
    for job in jobs:
        service_id = _parse_service_id_from_job(job)
        if service_id is None or service_id in latest:
            continue
        latest[service_id] = job
    return latest


@router.get("/eligible-servers", response_model=list[EligibleServiceServerRead])
def list_eligible_servers(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[EligibleServiceServerRead]:
    return [
        EligibleServiceServerRead(
            id=server.id,
            name=server.name,
            host=server.host,
            topology_name=topology.name if topology else None,
            topology_role=role.value if role else None,
        )
        for server, topology, role in _eligible_servers(db)
    ]


@router.get("", response_model=list[ExtraServiceRead])
def list_extra_services(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[ExtraServiceRead]:
    items = db.query(ServiceInstance).order_by(ServiceInstance.created_at.desc()).all()
    servers = db.query(Server).all()
    nodes = db.query(TopologyNode).all()
    topologies = {item.id: item for item in db.query(Topology).all()}
    server_by_id = {server.id: server for server in servers}
    node_by_server_id = {node.server_id: node for node in nodes}
    install_jobs_by_service_id = _latest_install_jobs_by_service_id(db)
    return [
        _hydrate_service_read(item, server_by_id, node_by_server_id, topologies, install_jobs_by_service_id)
        for item in items
    ]


@router.post("", response_model=ExtraServiceRead)
def create_extra_service(
    payload: ExtraServiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExtraServiceRead:
    if payload.service_type not in {"mtproxy", "socks5", "xray"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only MTProxy, SOCKS5 and Xray are supported right now")
    eligible = {server.id: (server, topology, role) for server, topology, role in _eligible_servers(db)}
    target = eligible.get(payload.server_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected server is not allowed for extra services")
    existing = next(
        (
            item
            for item in db.query(ServiceInstance).filter(ServiceInstance.server_id == payload.server_id).all()
            if item.service_type == payload.service_type
        ),
        None,
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This service is already registered on the selected server")
    server, _, _ = target
    try:
        if _server_has_named_service(server, payload.service_type):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{payload.service_type.upper()} is already present on this server. Import/adopt flow is required before a new install.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if payload.service_type == "mtproxy":
        domain = _validate_mtproxy_script_domain(payload.domain or "")
        config = {
            "repo_url": "https://github.com/TelegramMessenger/MTProxy",
            "port": 443,
            "domain": domain,
            "image_mode": "official_docker_fake_tls",
            "install_state": "planned",
        }
        endpoint = f"{server.host}:443"
    elif payload.service_type == "socks5":
        config = {
            "repo_url": "https://github.com/serjs/socks5-server",
            "image_mode": "docker_socks5_auth",
            "port": 1080,
            "install_state": "planned",
        }
        endpoint = f"{server.host}:1080"
    else:
        domain = _validate_xray_domain(payload.domain or "")
        config = {
            "repo_url": "https://github.com/XTLS/Xray-core",
            "image_mode": "docker_vless_reality",
            "mode": "vless_reality",
            "port": 443,
            "server_name": domain,
            "install_state": "planned",
        }
        endpoint = f"{server.host}:443"
    item = ServiceInstance(
        service_type=payload.service_type,
        server_id=payload.server_id,
        status="installing",
        config_json=json.dumps(config),
        public_endpoint=endpoint,
    )
    try:
        db.add(item)
        db.commit()
        db.refresh(item)

        job = DeploymentJob(
            job_type=JobType.INSTALL_EXTRA_SERVICE,
            status=JobStatus.PENDING,
            server_id=server.id,
            requested_by_user_id=current_user.id,
            result_message=f"ExtraService:{item.id}",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job.task_id = JobService().dispatch_job(job)
        db.add(job)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        if item.id:
            stale_item = db.query(ServiceInstance).filter(ServiceInstance.id == item.id).first()
            if stale_item:
                db.delete(stale_item)
                db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create MTProxy install job: {str(exc)}",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        if item.id:
            stale_item = db.query(ServiceInstance).filter(ServiceInstance.id == item.id).first()
            if stale_item:
                db.delete(stale_item)
                db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to dispatch MTProxy install job: {str(exc)}",
        ) from exc

    servers = db.query(Server).all()
    nodes = db.query(TopologyNode).all()
    topologies = {topology.id: topology for topology in db.query(Topology).all()}
    install_jobs_by_service_id = _latest_install_jobs_by_service_id(db)
    AuditService().log(
        db,
        action="extra_service.created",
        resource_type="extra_service",
        resource_id=str(item.id),
        details=f"{payload.service_type} install requested on {server.name}",
        user_id=current_user.id,
    )
    return _hydrate_service_read(
        item,
        {record.id: record for record in servers},
        {node.server_id: node for node in nodes},
        topologies,
        install_jobs_by_service_id,
    )


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_extra_service(
    service_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    item = db.query(ServiceInstance).filter(ServiceInstance.id == service_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extra service not found")
    server = db.query(Server).filter(Server.id == item.server_id).first()
    if server:
        try:
            if item.service_type == "mtproxy":
                _delete_mtproxy_from_server(item, server)
            elif item.service_type == "socks5":
                _delete_socks5_from_server(item, server)
            elif item.service_type == "xray":
                _delete_xray_from_server(item, server)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.delete(item)
    db.commit()
    AuditService().log(
        db,
        action="extra_service.deleted",
        resource_type="extra_service",
        resource_id=str(service_id),
        details="Extra service removed from panel",
        user_id=current_user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{service_id}/refresh-status", response_model=ExtraServiceRead)
def refresh_extra_service_status(
    service_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ExtraServiceRead:
    item = db.query(ServiceInstance).filter(ServiceInstance.id == service_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extra service not found")
    server = db.query(Server).filter(Server.id == item.server_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    if item.service_type not in {"mtproxy", "socks5", "xray"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only MTProxy, SOCKS5 and Xray refresh are supported right now")
    try:
        if item.service_type == "mtproxy":
            _refresh_mtproxy_service(db, item, server)
        elif item.service_type == "socks5":
            _refresh_socks5_service(db, item, server)
        else:
            _refresh_xray_service(db, item, server)
        db.commit()
        db.refresh(item)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    servers = db.query(Server).all()
    nodes = db.query(TopologyNode).all()
    topologies = {topology.id: topology for topology in db.query(Topology).all()}
    install_jobs_by_service_id = _latest_install_jobs_by_service_id(db)
    return _hydrate_service_read(
        item,
        {record.id: record for record in servers},
        {node.server_id: node for node in nodes},
        topologies,
        install_jobs_by_service_id,
    )


@router.post("/{service_id}/deliver-email")
def deliver_extra_service_email(
    service_id: int,
    payload: ExtraServiceDeliveryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    item = db.query(ServiceInstance).filter(ServiceInstance.id == service_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extra service not found")
    if item.service_type not in {"mtproxy", "socks5", "xray"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only MTProxy, SOCKS5 and Xray email delivery are supported right now")
    server = db.query(Server).filter(Server.id == item.server_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    target_email = payload.email.strip()
    if not target_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is required")
    try:
        if item.service_type == "mtproxy":
            detail = DeliveryService().send_mtproxy_email(db, item, server, target_email)
        elif item.service_type == "socks5":
            detail = DeliveryService().send_socks5_email(db, item, server, target_email)
        else:
            detail = DeliveryService().send_xray_email(db, item, server, target_email)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    AuditService().log(
        db,
        action="extra_service.delivered",
        resource_type="extra_service",
        resource_id=str(item.id),
        details=f"{item.service_type} access sent to {target_email}",
        user_id=current_user.id,
    )
    return {"email": "sent", "detail": detail}
