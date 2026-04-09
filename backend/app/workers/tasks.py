import asyncio
import json
import re
import secrets
import uuid
from pathlib import Path
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.backup import BackupJob, BackupStatus, BackupType
from app.models.agent_node import AgentNode
from app.models.agent_task import AgentTask
from app.models.client import Client
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.job import DeploymentJob, JobStatus, JobType
from app.models.server import AWGStatus, AccessStatus, InstallMethod, Server, ServerStatus
from app.models.service_instance import ServiceInstance
from app.models.topology import Topology, TopologyStatus, TopologyType
from app.models.topology_node import TopologyNode, TopologyNodeRole
from app.services.awg_detection import DETECT_AWG_COMMAND, parse_detection_output
from app.services.app_settings import AppSettingsService
from app.services.awg_profile import AWGProfileService
from app.services.full_bundle_backup import FullBundleBackupService
from app.services.bootstrap_commands import (
    BOOTSTRAP_SERVER_DOCKER_COMMAND,
    BOOTSTRAP_SERVER_GO_COMMAND,
    CHECK_SERVER_COMMAND,
    wrap_with_optional_sudo,
)
from app.services.client_sync import ClientSyncService
from app.services.panel_backup import PanelBackupService
from app.services.panel_restore import PanelRestoreService
from app.services.proxy_failover_agent import ProxyFailoverAgentService
from app.services.server_backup import ServerBackupService
from app.services.server_agent import ServerAgentService
from app.services.server_credentials import ServerCredentialsService
from app.services.server_restore import ServerRestoreService
from app.services.clients_table import ClientsTableService
from app.services.server_metrics import ServerMetricsService
from app.services.ssh import SSHService
from app.services.standard_config_inspector import StandardConfigInspector
from app.services.topology_deployer import deploy_topology_sync
from app.services.topology_renderer import TopologyRenderer
from app.workers.celery_app import celery_app


def _build_mtproxy_fake_tls_secret(domain: str, secret: str | None = None) -> str:
    normalized_domain = domain.strip().lower()
    if not normalized_domain:
        raise ValueError("Fake TLS domain is required")
    domain_hex = normalized_domain.encode("utf-8").hex()
    if len(domain_hex) > 30:
        raise ValueError("Fake TLS domain is too long for script-mode secret")
    raw = (secret or "").strip().lower()
    if raw.startswith("ee") and len(raw) == 32:
        return raw
    padding_len = 30 - len(domain_hex)
    random_hex = secrets.token_hex(15)[:padding_len]
    return f"ee{domain_hex}{random_hex}"


def _generate_socks5_username(existing: str | None = None) -> str:
    raw = (existing or "").strip()
    return raw or f"user{secrets.token_hex(4)}"


def _generate_socks5_password(existing: str | None = None) -> str:
    raw = (existing or "").strip()
    return raw or secrets.token_urlsafe(12)


def _build_xray_client_uri(
    *,
    host: str,
    port: int,
    uuid_value: str,
    server_name: str,
    public_key: str,
    short_id: str,
    remark: str,
) -> str:
    return (
        f"vless://{uuid_value}@{host}:{port}"
        f"?type=tcp&security=reality&encryption=none&flow=xtls-rprx-vision"
        f"&sni={server_name}&fp=safari&pbk={public_key}&sid={short_id}"
        f"#{remark}"
    )


def _extract_rendered_config_value(content: str, key: str) -> str | None:
    pattern = rf"^{re.escape(key)}\s*=\s*(.+)$"
    match = re.search(pattern, content, re.MULTILINE)
    return match.group(1).strip() if match else None


def _sync_panel_agent_from_local_status(agent: AgentNode, payload: dict[str, object] | None) -> bool:
    if payload is None:
        next_status = "offline"
        next_error = "Local agent status file is unavailable"
        changed = agent.status != next_status or agent.last_error != next_error
        agent.status = next_status
        agent.last_error = next_error
        return changed

    now = datetime.now(UTC)
    local_state = payload.get("local_state")
    capabilities = payload.get("capabilities")
    next_local_state = json.dumps(local_state, ensure_ascii=False) if local_state is not None else None
    next_capabilities = json.dumps(capabilities, ensure_ascii=False) if capabilities is not None else None
    next_status = str(payload.get("status") or "online")
    next_version = str(payload.get("version") or agent.version or "")
    changed = any(
        [
            agent.status != next_status,
            agent.version != next_version,
            agent.local_state_json != next_local_state,
            agent.capabilities_json != next_capabilities,
            agent.last_error is not None,
        ]
    )
    agent.status = next_status
    agent.version = next_version
    agent.local_state_json = next_local_state
    agent.capabilities_json = next_capabilities
    agent.last_seen_at = now
    agent.last_sync_at = now
    agent.last_error = None
    return changed


def _ensure_local_agent_task(db: Session, server: Server, agent: AgentNode, task_type: str) -> AgentTask | None:
    existing = (
        db.query(AgentTask)
        .filter(
            AgentTask.agent_id == agent.id,
            AgentTask.server_id == server.id,
            AgentTask.task_type == task_type,
            AgentTask.status.in_(["pending", "running"]),
        )
        .order_by(AgentTask.created_at.asc(), AgentTask.id.asc())
        .first()
    )
    if existing:
        return None
    task = AgentTask(
        agent_id=agent.id,
        server_id=server.id,
        task_type=task_type,
        status="pending",
        payload_json=None,
        requested_by_user_id=None,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _consume_completed_agent_task(
    db: Session,
    agent: AgentNode,
    server: Server,
    task_type: str,
) -> tuple[AgentTask | None, dict[str, object] | None]:
    task = (
        db.query(AgentTask)
        .filter(
            AgentTask.agent_id == agent.id,
            AgentTask.server_id == server.id,
            AgentTask.task_type == task_type,
            AgentTask.status == "succeeded",
        )
        .order_by(AgentTask.completed_at.desc(), AgentTask.id.desc())
        .first()
    )
    if task is None or not task.result_json:
        return None, None
    try:
        payload = json.loads(task.result_json)
    except json.JSONDecodeError:
        payload = None
    task.status = "consumed"
    db.add(task)
    return task, payload if isinstance(payload, dict) else None


def _persist_generated_standard_server_state(db: Session, topology: Topology | None, rendered_files: list) -> None:
    if not topology or topology.type not in {TopologyType.STANDARD, TopologyType.PROXY_EXIT, TopologyType.PROXY_MULTI_EXIT}:
        return
    profile_service = AWGProfileService()
    for rendered in rendered_files:
        server = db.query(Server).filter(Server.id == rendered.server_id).first()
        if not server:
            continue
        if rendered.metadata and rendered.metadata.get("preserve_server_runtime") == "1":
            # Service interfaces like awg10 must not replace the server's main awg0 live-state in the DB.
            continue
        if topology.type == TopologyType.STANDARD and server.config_source == "imported":
            continue
        try:
            runtime_details = json.loads(server.live_runtime_details_json) if server.live_runtime_details_json else {}
        except json.JSONDecodeError:
            runtime_details = {}
        if not isinstance(runtime_details, dict):
            runtime_details = {}

        runtime_details["config_preview"] = rendered.content
        runtime_details["config_path"] = rendered.remote_path
        runtime_details["peer_count"] = str(rendered.content.count("[Peer]"))

        if not (rendered.metadata and rendered.metadata.get("preserve_existing") == "1"):
            server.config_source = "generated"
        server.live_interface_name = rendered.interface_name
        server.live_config_path = rendered.remote_path
        server.live_address_cidr = _extract_rendered_config_value(rendered.content, "Address")
        listen_port_raw = _extract_rendered_config_value(rendered.content, "ListenPort")
        server.live_listen_port = int(listen_port_raw) if listen_port_raw and listen_port_raw.isdigit() else None
        server.live_peer_count = rendered.content.count("[Peer]")
        server.live_runtime_details_json = json.dumps(runtime_details)
        profile_service.copy_profile_metadata(topology, server)
        db.add(server)


def _update_job(job_id: int, *, status: JobStatus, result_message: str) -> None:
    db: Session = SessionLocal()
    try:
        job = db.query(DeploymentJob).filter(DeploymentJob.id == job_id).first()
        if not job:
            return
        job.status = status
        job.result_message = result_message
        db.add(job)
        db.commit()
    finally:
        db.close()


def _update_job_message(job_id: int, result_message: str) -> None:
    db: Session = SessionLocal()
    try:
        job = db.query(DeploymentJob).filter(DeploymentJob.id == job_id).first()
        if not job:
            return
        job.result_message = result_message
        db.add(job)
        db.commit()
    finally:
        db.close()


def _stale_job_timeout(job: DeploymentJob) -> timedelta:
    if job.job_type == JobType.DEPLOY_TOPOLOGY:
        return timedelta(minutes=20)
    if job.job_type == JobType.BOOTSTRAP_SERVER:
        return timedelta(minutes=45)
    if job.job_type == JobType.BACKUP:
        return timedelta(minutes=30)
    return timedelta(minutes=10)


def _refresh_server_live_runtime_state(db: Session, server: Server) -> None:
    # Bootstrap and re-check should converge to the same live runtime snapshot used by clients/topologies.
    inspection = asyncio.run(StandardConfigInspector().inspect(server))
    server.config_source = "imported" if inspection.interface or inspection.listen_port or inspection.peer_count else "generated"
    server.live_interface_name = inspection.interface or server.live_interface_name or "awg0"
    server.live_config_path = inspection.config_path or server.live_config_path
    server.live_address_cidr = inspection.address_cidr or server.live_address_cidr
    server.live_listen_port = inspection.listen_port if inspection.listen_port is not None else server.live_listen_port
    server.live_peer_count = inspection.peer_count
    server.live_runtime_details_json = inspection.raw_json or server.live_runtime_details_json


def _load_job_and_server(job_id: int) -> tuple[Session, DeploymentJob | None, Server | None]:
    db: Session = SessionLocal()
    job = db.query(DeploymentJob).filter(DeploymentJob.id == job_id).first()
    server = None
    if job and job.server_id:
        server = db.query(Server).filter(Server.id == job.server_id).first()
    return db, job, server


def _load_job_service_and_server(job_id: int) -> tuple[Session, DeploymentJob | None, ServiceInstance | None, Server | None]:
    db: Session = SessionLocal()
    job = db.query(DeploymentJob).filter(DeploymentJob.id == job_id).first()
    service = None
    server = None
    if job and job.result_message and job.result_message.startswith("ExtraService:"):
        raw_tail = job.result_message.split(":", maxsplit=1)[1]
        raw_id = raw_tail.split("|", maxsplit=1)[0].strip()
        if raw_id.isdigit():
            service_id = int(raw_id)
            service = db.query(ServiceInstance).filter(ServiceInstance.id == service_id).first()
            if service:
                server = db.query(Server).filter(Server.id == service.server_id).first()
    return db, job, service, server


def _latest_install_job_for_service(db: Session, service_id: int) -> DeploymentJob | None:
    jobs = (
        db.query(DeploymentJob)
        .filter(DeploymentJob.job_type == JobType.INSTALL_EXTRA_SERVICE)
        .order_by(DeploymentJob.updated_at.desc(), DeploymentJob.id.desc())
        .all()
    )
    for job in jobs:
        if not job.result_message or not job.result_message.startswith("ExtraService:"):
            continue
        raw_tail = job.result_message.split(":", maxsplit=1)[1]
        raw_id = raw_tail.split("|", maxsplit=1)[0].strip()
        if raw_id.isdigit() and int(raw_id) == service_id:
            return job
    return None


def _sync_mtproxy_service(db: Session, service: ServiceInstance, server: Server) -> None:
    creds = ServerCredentialsService()
    ssh = SSHService()
    config = json.loads(service.config_json) if service.config_json else {}
    runtime = json.loads(service.runtime_details_json) if service.runtime_details_json else {}
    port = int(config.get("port") or 443)
    container_name = str(runtime.get("container_name") or config.get("container_name") or f"awg-mtproxy-{service.id}")
    image_name = str(runtime.get("image_name") or config.get("image_name") or "telegrammessenger/proxy:latest")
    remote_dir = str(runtime.get("remote_dir") or config.get("remote_dir") or f"/opt/awg-extra-services/mtproxy-{service.id}")
    domain = str(config.get("domain") or "").strip()
    secret = str(config.get("secret") or "").strip().lower()
    if not secret:
        secret = _build_mtproxy_fake_tls_secret(domain)
    tg_url = str(config.get("tg_url") or "")
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
        ssh.run_command(
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

    latest_job = _latest_install_job_for_service(db, service.id)

    if remote_status == "running":
        if not secret:
            secret = _build_mtproxy_fake_tls_secret(domain)
        if not tg_url:
            tg_url = f"tg://proxy?server={server.host}&port={port}&secret={secret}"
        config.update(
            {
                "repo_url": "https://github.com/TelegramMessenger/MTProxy",
                "image_mode": "official_docker_fake_tls",
                "port": port,
                "domain": domain or None,
                "secret": secret,
                "tg_url": tg_url,
                "container_name": container_name,
                "image_name": image_name,
                "remote_dir": remote_dir,
                "install_state": "installed",
            }
        )
        service.status = "running"
        service.public_endpoint = f"{server.host}:{port}"
        service.config_json = json.dumps(config)
        service.runtime_details_json = json.dumps(
            {
                "container_name": container_name,
                "image_name": image_name,
                "remote_dir": remote_dir,
                "container_status": remote_status,
            }
        )
        service.last_error = None
        db.add(service)
        if latest_job and latest_job.status in {JobStatus.PENDING, JobStatus.RUNNING, JobStatus.FAILED}:
            latest_job.status = JobStatus.SUCCEEDED
            latest_job.result_message = f"ExtraService:{service.id}|MTProxy confirmed running on {server.name}"
            db.add(latest_job)
        return

    if remote_status in {"created", "restarting", "paused"}:
        service.status = "installing"
    elif remote_status in {"exited", "dead", "missing"}:
        service.status = "error"
        service.last_error = f"MTProxy container state: {remote_status}"
    else:
        service.status = remote_status
    runtime.update(
        {
            "container_name": container_name,
            "image_name": image_name,
            "remote_dir": remote_dir,
            "container_status": remote_status,
        }
    )
    service.runtime_details_json = json.dumps(runtime)
    db.add(service)
    if latest_job and latest_job.status in {JobStatus.PENDING, JobStatus.RUNNING} and remote_status in {"exited", "dead", "missing"}:
        latest_job.status = JobStatus.FAILED
        latest_job.result_message = f"ExtraService:{service.id}|MTProxy container state: {remote_status}"
        db.add(latest_job)


def _sync_socks5_service(db: Session, service: ServiceInstance, server: Server) -> None:
    creds = ServerCredentialsService()
    ssh = SSHService()
    config = json.loads(service.config_json) if service.config_json else {}
    runtime = json.loads(service.runtime_details_json) if service.runtime_details_json else {}
    port = int(config.get("port") or 1080)
    container_name = str(runtime.get("container_name") or config.get("container_name") or f"awg-socks5-{service.id}")
    image_name = str(runtime.get("image_name") or config.get("image_name") or "serjs/go-socks5-proxy:latest")
    remote_dir = str(runtime.get("remote_dir") or config.get("remote_dir") or f"/opt/awg-extra-services/socks5-{service.id}")
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
        ssh.run_command(
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

    latest_job = _latest_install_job_for_service(db, service.id)

    if remote_status == "running":
        config.update(
            {
                "repo_url": "https://github.com/serjs/socks5-server",
                "image_mode": "docker_socks5_auth",
                "port": port,
                "container_name": container_name,
                "image_name": image_name,
                "remote_dir": remote_dir,
                "install_state": "installed",
            }
        )
        service.status = "running"
        service.public_endpoint = f"{server.host}:{port}"
        service.config_json = json.dumps(config)
        service.runtime_details_json = json.dumps(
            {
                "container_name": container_name,
                "image_name": image_name,
                "remote_dir": remote_dir,
                "container_status": remote_status,
            }
        )
        service.last_error = None
        db.add(service)
        if latest_job and latest_job.status in {JobStatus.PENDING, JobStatus.RUNNING, JobStatus.FAILED}:
            latest_job.status = JobStatus.SUCCEEDED
            latest_job.result_message = f"ExtraService:{service.id}|SOCKS5 confirmed running on {server.name}"
            db.add(latest_job)
        return

    if remote_status in {"created", "restarting", "paused"}:
        service.status = "installing"
    elif remote_status in {"exited", "dead", "missing"}:
        service.status = "error"
        service.last_error = f"SOCKS5 container state: {remote_status}"
    else:
        service.status = remote_status
    runtime.update(
        {
            "container_name": container_name,
            "image_name": image_name,
            "remote_dir": remote_dir,
            "container_status": remote_status,
        }
    )
    service.runtime_details_json = json.dumps(runtime)
    db.add(service)
    if latest_job and latest_job.status in {JobStatus.PENDING, JobStatus.RUNNING} and remote_status in {"exited", "dead", "missing"}:
        latest_job.status = JobStatus.FAILED
        latest_job.result_message = f"ExtraService:{service.id}|SOCKS5 container state: {remote_status}"
        db.add(latest_job)


def _sync_xray_service(db: Session, service: ServiceInstance, server: Server) -> None:
    creds = ServerCredentialsService()
    ssh = SSHService()
    config = json.loads(service.config_json) if service.config_json else {}
    runtime = json.loads(service.runtime_details_json) if service.runtime_details_json else {}
    port = int(config.get("port") or 443)
    container_name = str(runtime.get("container_name") or config.get("container_name") or f"awg-xray-{service.id}")
    image_name = str(runtime.get("image_name") or config.get("image_name") or "ghcr.io/xtls/xray-core:latest")
    remote_dir = str(runtime.get("remote_dir") or config.get("remote_dir") or f"/opt/awg-extra-services/xray-{service.id}")
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
        ssh.run_command(
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

    latest_job = _latest_install_job_for_service(db, service.id)

    if remote_status == "running":
        config.update(
            {
                "repo_url": "https://github.com/XTLS/Xray-core",
                "image_mode": "docker_vless_reality",
                "mode": "vless_reality",
                "port": port,
                "container_name": container_name,
                "image_name": image_name,
                "remote_dir": remote_dir,
                "install_state": "installed",
            }
        )
        service.status = "running"
        service.public_endpoint = f"{server.host}:{port}"
        service.config_json = json.dumps(config)
        service.runtime_details_json = json.dumps(
            {
                "container_name": container_name,
                "image_name": image_name,
                "remote_dir": remote_dir,
                "container_status": remote_status,
            }
        )
        service.last_error = None
        db.add(service)
        if latest_job and latest_job.status in {JobStatus.PENDING, JobStatus.RUNNING, JobStatus.FAILED}:
            latest_job.status = JobStatus.SUCCEEDED
            latest_job.result_message = f"ExtraService:{service.id}|Xray confirmed running on {server.name}"
            db.add(latest_job)
        return

    if remote_status in {"created", "restarting", "paused"}:
        service.status = "installing"
    elif remote_status in {"exited", "dead", "missing"}:
        service.status = "error"
        service.last_error = f"Xray container state: {remote_status}"
    else:
        service.status = remote_status
    runtime.update(
        {
            "container_name": container_name,
            "image_name": image_name,
            "remote_dir": remote_dir,
            "container_status": remote_status,
        }
    )
    service.runtime_details_json = json.dumps(runtime)
    db.add(service)
    if latest_job and latest_job.status in {JobStatus.PENDING, JobStatus.RUNNING} and remote_status in {"exited", "dead", "missing"}:
        latest_job.status = JobStatus.FAILED
        latest_job.result_message = f"ExtraService:{service.id}|Xray container state: {remote_status}"
        db.add(latest_job)


@celery_app.task(name="app.workers.tasks.install_extra_service")
def install_extra_service(job_id: int) -> None:
    db, job, service, server = _load_job_service_and_server(job_id)
    if not job or not service or not server:
        db.close()
        return
    try:
        job.status = JobStatus.RUNNING
        job.result_message = f"ExtraService:{service.id}|installing"
        service.status = "installing"
        db.add_all([job, service])
        db.commit()

        creds = ServerCredentialsService()
        ssh = SSHService()
        config = json.loads(service.config_json) if service.config_json else {}
        if service.service_type == "mtproxy":
            port = int(config.get("port") or 443)
            stats_port = int(config.get("stats_port") or 8888)
            domain = str(config.get("domain") or "").strip()
            secret = _build_mtproxy_fake_tls_secret(domain, str(config.get("secret") or ""))
            remote_dir = f"/opt/awg-extra-services/mtproxy-{service.id}"
            container_name = f"awg-mtproxy-{service.id}"
            image_name = "telegrammessenger/proxy:latest"
            tg_url = f"tg://proxy?server={server.host}&port={port}&secret={secret}"
        elif service.service_type == "socks5":
            port = int(config.get("port") or 1080)
            stats_port = 0
            domain = ""
            secret = ""
            remote_dir = f"/opt/awg-extra-services/socks5-{service.id}"
            container_name = f"awg-socks5-{service.id}"
            image_name = "serjs/go-socks5-proxy:latest"
            tg_url = ""
            username = _generate_socks5_username(str(config.get("username") or ""))
            password = _generate_socks5_password(str(config.get("password") or ""))
        elif service.service_type == "xray":
            port = int(config.get("port") or 443)
            stats_port = 0
            domain = str(config.get("server_name") or "").strip()
            secret = ""
            remote_dir = f"/opt/awg-extra-services/xray-{service.id}"
            container_name = f"awg-xray-{service.id}"
            image_name = "ghcr.io/xtls/xray-core:latest"
            tg_url = ""
            uuid_value = str(config.get("uuid") or uuid.uuid4())
            short_id = str(config.get("short_id") or secrets.token_hex(4))
        else:
            raise RuntimeError(f"Unsupported extra service type: {service.service_type}")

        prep_command = wrap_with_optional_sudo(
            f"""
set -e
mkdir -p {remote_dir}/data
if ! command -v docker >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y docker.io ca-certificates curl git
    systemctl enable docker || true
    systemctl restart docker || service docker restart || true
  else
    echo "Docker is required for MTProxy install and automatic installation is supported only on apt-based hosts" >&2
    exit 1
  fi
fi
docker rm -f {container_name} >/dev/null 2>&1 || true
""".strip(),
            creds.get_sudo_password(server),
        )
        prep_result = asyncio.run(
            ssh.run_command(
                host=server.host,
                username=server.ssh_user,
                port=server.ssh_port,
                password=creds.get_ssh_password(server),
                private_key=creds.get_private_key(server),
                command=prep_command,
                timeout_seconds=900,
            )
        )
        if prep_result.exit_status != 0:
            raise RuntimeError(prep_result.stderr.strip() or prep_result.stdout.strip() or f"{service.service_type} prepare failed")

        install_command = wrap_with_optional_sudo(
            (
                f"""
set -e
docker rm -f {container_name} >/dev/null 2>&1 || true
docker pull {image_name}
docker run -d \
  --name {container_name} \
  --restart unless-stopped \
  -p {port}:443/tcp \
  -e SECRET={secret} \
  {image_name}
docker ps --filter name={container_name} --format '{{{{.Names}}}}'
""".strip()
                if service.service_type == "mtproxy"
                else f"""
set -e
docker rm -f {container_name} >/dev/null 2>&1 || true
docker pull {image_name}
docker run -d \
  --name {container_name} \
  --restart unless-stopped \
  -p {port}:1080/tcp \
  -e PROXY_PORT=1080 \
  -e PROXY_USER="{username}" \
  -e PROXY_PASSWORD="{password}" \
  {image_name}
docker ps --filter name={container_name} --format '{{{{.Names}}}}'
""".strip()
                if service.service_type == "socks5"
                else f"""
set -e
docker rm -f {container_name} >/dev/null 2>&1 || true
docker pull {image_name}
mkdir -p {remote_dir}
key_output="$(docker run --rm {image_name} x25519 2>/dev/null || true)"
private_key="$(printf '%s\n' "$key_output" | awk -F': ' '/Private key/ {{print $2}}' | head -n1)"
if [ -z "$private_key" ]; then
  private_key="$(printf '%s\n' "$key_output" | awk -F': ' '/PrivateKey/ {{print $2}}' | head -n1)"
fi
public_key="$(printf '%s\n' "$key_output" | awk -F': ' '/Public key/ {{print $2}}' | head -n1)"
if [ -z "$public_key" ]; then
  public_key="$(printf '%s\n' "$key_output" | awk -F': ' '/Password \\(PublicKey\\)/ {{print $2}}' | head -n1)"
fi
if [ -z "$private_key" ] || [ -z "$public_key" ]; then
  echo "Unable to generate x25519 keypair" >&2
  exit 1
fi
cat > {remote_dir}/config.json <<'EOF'
{{
  "log": {{
    "loglevel": "warning"
  }},
  "inbounds": [
    {{
      "port": {port},
      "protocol": "vless",
      "settings": {{
        "clients": [
          {{
            "id": "{uuid_value}",
            "flow": "xtls-rprx-vision"
          }}
        ],
        "decryption": "none"
      }},
      "streamSettings": {{
        "network": "tcp",
        "security": "reality",
        "realitySettings": {{
          "show": false,
          "dest": "{domain}:443",
          "serverNames": ["{domain}"],
          "privateKey": "__PRIVATE_KEY__",
          "shortIds": ["{short_id}"]
        }}
      }}
    }}
  ],
  "outbounds": [
    {{
      "protocol": "freedom"
    }}
  ]
}}
EOF
sed -i "s#__PRIVATE_KEY__#$private_key#g" {remote_dir}/config.json
docker run -d \
  --name {container_name} \
  --restart unless-stopped \
  -p {port}:{port}/tcp \
  -v {remote_dir}/config.json:/usr/local/etc/xray/config.json:ro \
  {image_name} run -c /usr/local/etc/xray/config.json
docker ps --filter name={container_name} --format '{{{{.Names}}}}'
printf '\nXRAY_PUBLIC_KEY=%s\n' "$public_key"
""".strip()
            ),
            creds.get_sudo_password(server),
        )
        install_result = asyncio.run(
            ssh.run_command(
                host=server.host,
                username=server.ssh_user,
                port=server.ssh_port,
                password=creds.get_ssh_password(server),
                private_key=creds.get_private_key(server),
                command=install_command,
                timeout_seconds=3600,
            )
        )
        if install_result.exit_status != 0:
            raise RuntimeError(install_result.stderr.strip() or install_result.stdout.strip() or f"{service.service_type} install failed")

        if service.service_type == "mtproxy":
            config.update(
                {
                    "repo_url": "https://github.com/TelegramMessenger/MTProxy",
                    "image_mode": "official_docker_fake_tls",
                    "port": port,
                    "domain": domain or None,
                    "secret": secret,
                    "tg_url": tg_url,
                    "remote_dir": remote_dir,
                    "container_name": container_name,
                    "image_name": image_name,
                    "install_state": "installed",
                }
            )
            success_message = f"ExtraService:{service.id}|MTProxy installed on {server.name}"
        elif service.service_type == "socks5":
            config.update(
                {
                    "repo_url": "https://github.com/serjs/socks5-server",
                    "image_mode": "docker_socks5_auth",
                    "port": port,
                    "username": username,
                    "password": password,
                    "remote_dir": remote_dir,
                    "container_name": container_name,
                    "image_name": image_name,
                    "install_state": "installed",
                }
            )
            success_message = f"ExtraService:{service.id}|SOCKS5 installed on {server.name}"
        else:
            public_key = ""
            for line in install_result.stdout.splitlines():
                if line.startswith("XRAY_PUBLIC_KEY="):
                    public_key = line.split("=", maxsplit=1)[1].strip()
                    break
            if not public_key:
                raise RuntimeError("Xray public key was not returned by installer")
            client_uri = _build_xray_client_uri(
                host=server.host,
                port=port,
                uuid_value=uuid_value,
                server_name=domain,
                public_key=public_key,
                short_id=short_id,
                remark=f"{server.name}-Reality",
            )
            config.update(
                {
                    "repo_url": "https://github.com/XTLS/Xray-core",
                    "image_mode": "docker_vless_reality",
                    "mode": "vless_reality",
                    "port": port,
                    "server_name": domain,
                    "uuid": uuid_value,
                    "public_key": public_key,
                    "short_id": short_id,
                    "client_uri": client_uri,
                    "remote_dir": remote_dir,
                    "container_name": container_name,
                    "image_name": image_name,
                    "install_state": "installed",
                }
            )
            success_message = f"ExtraService:{service.id}|Xray installed on {server.name}"
        service.status = "running"
        service.public_endpoint = f"{server.host}:{port}"
        service.config_json = json.dumps(config)
        service.runtime_details_json = json.dumps(
            {
                "container_name": container_name,
                "image_name": image_name,
                "remote_dir": remote_dir,
                "stats_port": stats_port,
            }
        )
        service.last_error = None
        job.status = JobStatus.SUCCEEDED
        job.result_message = success_message
        db.add_all([job, service])
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job.status = JobStatus.FAILED
        job.result_message = f"ExtraService:{service.id}|{str(exc)}"
        service.status = "error"
        service.last_error = str(exc)
        db.add_all([job, service])
        db.commit()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.bootstrap_server")
def bootstrap_server(job_id: int) -> None:
    # Installs the selected panel-managed AWG runtime on a target node over SSH.
    db, job, server = _load_job_and_server(job_id)
    if not job or not server:
        db.close()
        return

    try:
        job.status = JobStatus.RUNNING
        job.result_message = "Bootstrap started"
        db.add(job)
        db.commit()

        creds = ServerCredentialsService()
        if server.install_method == InstallMethod.DOCKER:
            bootstrap_command = BOOTSTRAP_SERVER_DOCKER_COMMAND
        elif server.install_method in {InstallMethod.GO, InstallMethod.NATIVE, InstallMethod.UNKNOWN}:
            bootstrap_command = BOOTSTRAP_SERVER_GO_COMMAND
        else:
            raise RuntimeError("Bootstrap is supported only for docker and go install methods")

        command = wrap_with_optional_sudo(bootstrap_command, creds.get_sudo_password(server))
        result = asyncio.run(
            SSHService().run_command(
                host=server.host,
                username=server.ssh_user,
                port=server.ssh_port,
                password=creds.get_ssh_password(server),
                private_key=creds.get_private_key(server),
                command=command,
                timeout_seconds=1800,
            )
        )
        if result.exit_status == 0:
            detect_result = asyncio.run(
                SSHService().run_command(
                    host=server.host,
                    username=server.ssh_user,
                    port=server.ssh_port,
                    password=creds.get_ssh_password(server),
                    private_key=creds.get_private_key(server),
                    command=DETECT_AWG_COMMAND,
                    timeout_seconds=120,
                )
            )
            if detect_result.exit_status != 0:
                raise RuntimeError(detect_result.stderr.strip() or detect_result.stdout.strip() or "AWG detection failed after bootstrap")
            parsed = parse_detection_output(detect_result.stdout)
            job.status = JobStatus.SUCCEEDED
            job.result_message = result.stdout.strip() or "Bootstrap completed"
            server.status = ServerStatus.HEALTHY
            server.access_status = AccessStatus.OK
            server.awg_status = AWGStatus.DETECTED if parsed.detected else AWGStatus.MISSING
            server.install_method = InstallMethod(parsed.install_type)
            server.runtime_flavor = parsed.runtime_flavor
            server.awg_detected = parsed.detected
            server.awg_version = parsed.version
            server.os_name = parsed.os_name or server.os_name
            server.os_version = parsed.os_version or server.os_version
            server.awg_interfaces_json = parsed.interfaces_json
            server.ready_for_topology = parsed.detected
            server.last_error = None
            if parsed.detected:
                try:
                    _refresh_server_live_runtime_state(db, server)
                except Exception:
                    # Bootstrap should still succeed if live config inspection is temporarily unavailable.
                    pass
                agent_service = ServerAgentService()
                agent = agent_service.ensure_enrolled(db, server)
                asyncio.run(agent_service.install(server, agent))
        else:
            detect_result = asyncio.run(
                SSHService().run_command(
                    host=server.host,
                    username=server.ssh_user,
                    port=server.ssh_port,
                    password=creds.get_ssh_password(server),
                    private_key=creds.get_private_key(server),
                    command=DETECT_AWG_COMMAND,
                    timeout_seconds=120,
                )
            )
            if detect_result.exit_status == 0:
                parsed = parse_detection_output(detect_result.stdout)
                if parsed.detected:
                    job.status = JobStatus.SUCCEEDED
                    bootstrap_warning = result.stderr.strip() or result.stdout.strip() or "Bootstrap completed with warnings"
                    job.result_message = f"Bootstrap completed with warning: {bootstrap_warning}"
                    server.status = ServerStatus.HEALTHY
                    server.access_status = AccessStatus.OK
                    server.awg_status = AWGStatus.DETECTED
                    server.install_method = InstallMethod(parsed.install_type)
                    server.runtime_flavor = parsed.runtime_flavor
                    server.awg_detected = True
                    server.awg_version = parsed.version
                    server.os_name = parsed.os_name or server.os_name
                    server.os_version = parsed.os_version or server.os_version
                    server.awg_interfaces_json = parsed.interfaces_json
                    server.ready_for_topology = True
                    server.last_error = bootstrap_warning
                    try:
                        _refresh_server_live_runtime_state(db, server)
                    except Exception:
                        pass
                else:
                    job.status = JobStatus.FAILED
                    job.result_message = result.stderr.strip() or result.stdout.strip() or "Bootstrap failed"
                    server.status = ServerStatus.ERROR
                    server.last_error = job.result_message
                    server.ready_for_topology = False
            else:
                job.status = JobStatus.FAILED
                job.result_message = result.stderr.strip() or result.stdout.strip() or "Bootstrap failed"
                server.status = ServerStatus.ERROR
                server.last_error = job.result_message
                server.ready_for_topology = False
        server.last_checked_at = datetime.now(UTC)
        db.add_all([job, server])
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job.status = JobStatus.FAILED
        job.result_message = str(exc)
        server.status = ServerStatus.ERROR
        server.last_error = str(exc)
        server.last_checked_at = datetime.now(UTC)
        db.add_all([job, server])
        db.commit()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.check_server")
def check_server(job_id: int) -> None:
    # Minimal connectivity and host capability check before bootstrap/deploy.
    db, job, server = _load_job_and_server(job_id)
    if not job or not server:
        db.close()
        return

    try:
        job.status = JobStatus.RUNNING
        job.result_message = "Server check started"
        db.add(job)
        db.commit()

        creds = ServerCredentialsService()
        result = asyncio.run(
            SSHService().run_command(
                host=server.host,
                username=server.ssh_user,
                port=server.ssh_port,
                password=creds.get_ssh_password(server),
                private_key=creds.get_private_key(server),
                command=CHECK_SERVER_COMMAND,
            )
        )
        if result.exit_status == 0:
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            job.status = JobStatus.SUCCEEDED
            job.result_message = result.stdout.strip() or "Server check completed"
            server.status = ServerStatus.HEALTHY
            server.access_status = AccessStatus.OK
            server.os_name = payload.get("os_name") or server.os_name
            server.os_version = payload.get("os_version") or server.os_version
            server.last_error = None
        else:
            job.status = JobStatus.FAILED
            job.result_message = result.stderr.strip() or result.stdout.strip() or "Server check failed"
            server.status = ServerStatus.ERROR
            server.access_status = AccessStatus.FAILED
            server.last_error = job.result_message
        server.ready_for_topology = False
        server.last_checked_at = datetime.now(UTC)
        db.add_all([job, server])
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job.status = JobStatus.FAILED
        job.result_message = str(exc)
        server.status = ServerStatus.ERROR
        server.access_status = AccessStatus.FAILED
        server.last_error = str(exc)
        server.last_checked_at = datetime.now(UTC)
        server.ready_for_topology = False
        db.add_all([job, server])
        db.commit()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.deploy_topology")
def deploy_topology(job_id: int) -> None:
    # Applies rendered proxy<->exit configs to the servers participating in the topology.
    db: Session = SessionLocal()
    try:
        job = db.query(DeploymentJob).filter(DeploymentJob.id == job_id).first()
        if not job or not job.topology_id:
            return

        topology = db.query(Topology).filter(Topology.id == job.topology_id).first()
        nodes = db.query(TopologyNode).filter(TopologyNode.topology_id == job.topology_id).all()
        server_ids = [node.server_id for node in nodes]
        servers = db.query(Server).filter(Server.id.in_(server_ids)).all() if server_ids else []
        clients = db.query(Client).filter(Client.topology_id == job.topology_id).order_by(Client.created_at.asc()).all()
        servers_by_id = {server.id: server for server in servers}

        job.status = JobStatus.RUNNING
        job.result_message = "Topology rendering started"
        if topology:
            topology.status = TopologyStatus.PENDING
            db.add(topology)
        db.add(job)
        db.commit()

        rendered_files = deploy_topology_sync(
            topology,
            nodes,
            servers_by_id,
            clients,
            progress_callback=lambda message: _update_job_message(job_id, message),
        )
        _persist_generated_standard_server_state(db, topology, rendered_files)
        result_lines = [f"{item.remote_path}: {len(item.content.splitlines())} lines" for item in rendered_files]

        job.status = JobStatus.SUCCEEDED
        job.result_message = "Applied configs:\n" + "\n".join(result_lines)
        if topology:
            topology.status = TopologyStatus.APPLIED
            if topology.type in {TopologyType.PROXY_EXIT, TopologyType.PROXY_MULTI_EXIT}:
                primary_exit = next(
                    (node for node in sorted(nodes, key=lambda item: item.priority) if node.role == TopologyNodeRole.EXIT),
                    None,
                )
                topology.active_exit_server_id = primary_exit.server_id if primary_exit else topology.active_exit_server_id
            db.add(topology)
        db.add(job)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.query(DeploymentJob).filter(DeploymentJob.id == job_id).first()
        topology = db.query(Topology).filter(Topology.id == job.topology_id).first() if job and job.topology_id else None
        if job:
            error_message = str(exc).strip() or f"{type(exc).__name__} raised during topology deploy"
            job.status = JobStatus.FAILED
            job.result_message = error_message
            db.add(job)
            if topology:
                topology.status = TopologyStatus.ERROR
                db.add(topology)
            db.commit()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.detect_awg")
def detect_awg(job_id: int) -> None:
    # Detects whether the expected native AWG binaries are already present on the host.
    db, job, server = _load_job_and_server(job_id)
    if not job or not server:
        db.close()
        return

    try:
        job.status = JobStatus.RUNNING
        job.result_message = "AWG detection started"
        db.add(job)
        db.commit()

        creds = ServerCredentialsService()
        result = asyncio.run(
            SSHService().run_command(
                host=server.host,
                username=server.ssh_user,
                port=server.ssh_port,
                password=creds.get_ssh_password(server),
                private_key=creds.get_private_key(server),
                command=DETECT_AWG_COMMAND,
            )
        )
        if result.exit_status != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "AWG detection failed")

        parsed = parse_detection_output(result.stdout)
        server.awg_detected = parsed.detected
        server.awg_version = parsed.version
        server.os_name = parsed.os_name or server.os_name
        server.os_version = parsed.os_version or server.os_version
        server.install_method = InstallMethod(parsed.install_type)
        server.runtime_flavor = parsed.runtime_flavor
        server.awg_interfaces_json = parsed.interfaces_json
        server.last_checked_at = datetime.now(UTC)
        server.access_status = AccessStatus.OK
        server.awg_status = AWGStatus.DETECTED if parsed.detected else AWGStatus.MISSING
        server.last_error = None if parsed.detected else "AWG runtime not detected"
        server.status = ServerStatus.HEALTHY if parsed.detected else ServerStatus.DEGRADED
        server.ready_for_topology = parsed.detected

        job.status = JobStatus.SUCCEEDED
        job.result_message = result.stdout.strip()
        db.add_all([job, server])
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job.status = JobStatus.FAILED
        job.result_message = str(exc)
        server.status = ServerStatus.ERROR
        server.awg_status = AWGStatus.UNKNOWN
        server.last_error = str(exc)
        server.last_checked_at = datetime.now(UTC)
        server.ready_for_topology = False
        db.add_all([job, server])
        db.commit()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.run_backup")
def run_backup(job_id: int) -> None:
    # Backup worker currently supports panel DB dumps and restore-ready server archives.
    db: Session = SessionLocal()
    backup_job_id: int | None = None
    try:
        job = db.query(DeploymentJob).filter(DeploymentJob.id == job_id).first()
        if not job:
            return

        if job.result_message and job.result_message.startswith("BackupJob:"):
            backup_job_id = int(job.result_message.split(":", maxsplit=1)[1])
        backup_job = db.query(BackupJob).filter(BackupJob.id == backup_job_id).first() if backup_job_id else None

        job.status = JobStatus.RUNNING
        job.result_message = "Backup started"
        db.add(job)
        db.commit()
        if backup_job:
            backup_job.status = BackupStatus.RUNNING
            db.add(backup_job)
            db.commit()

        backup_dir = Path(settings.backup_storage_path)
        if not backup_job:
            raise RuntimeError("Backup job payload is missing")

        if backup_job.backup_type.value == "server":
            if not backup_job.server_id:
                raise RuntimeError("Server backup requires server_id")

            server = db.query(Server).filter(Server.id == backup_job.server_id).first()
            if not server:
                raise RuntimeError("Server for backup was not found")

            bundle = asyncio.run(ServerBackupService().create_backup(server, backup_job.id, backup_dir))
            backup_job.result_message = "Server backup archive created"
        elif backup_job.backup_type.value == "database":
            bundle = PanelBackupService().create_backup(backup_job.id, backup_dir)
            backup_job.result_message = "Panel backup archive created"
        elif backup_job.backup_type.value == "full":
            servers = (
                db.query(Server)
                .filter(Server.live_runtime_details_json.is_not(None))
                .order_by(Server.created_at.asc())
                .all()
            )
            bundle = asyncio.run(FullBundleBackupService().create_backup(backup_job.id, backup_dir, servers))
            backup_job.result_message = "Full bundle backup archive created"
        else:
            raise RuntimeError(f"Backup type {backup_job.backup_type.value} is not implemented yet")

        job.status = JobStatus.SUCCEEDED
        job.result_message = bundle.result_message
        db.add(job)

        backup_job.status = BackupStatus.SUCCEEDED
        backup_job.storage_path = str(bundle.archive_path)
        db.add(backup_job)

        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.query(DeploymentJob).filter(DeploymentJob.id == job_id).first()
        if job:
            backup_job = db.query(BackupJob).filter(BackupJob.id == backup_job_id).first() if backup_job_id else None
            job.status = JobStatus.FAILED
            job.result_message = str(exc)
            db.add(job)
            if backup_job:
                backup_job.status = BackupStatus.FAILED
                backup_job.result_message = str(exc)
                db.add(backup_job)
            db.commit()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.restore_server_backup")
def restore_server_backup(job_id: int) -> None:
    db: Session = SessionLocal()
    backup_job_id: int | None = None
    bundle_server_id: int | None = None
    try:
        job = db.query(DeploymentJob).filter(DeploymentJob.id == job_id).first()
        if not job:
            return
        if job.result_message and job.result_message.startswith("RestoreBackupJob:"):
            parts = job.result_message.split(":")
            if len(parts) >= 2:
                backup_job_id = int(parts[1])
            if len(parts) >= 3:
                bundle_server_id = int(parts[2])
        backup_job = db.query(BackupJob).filter(BackupJob.id == backup_job_id).first() if backup_job_id else None

        job.status = JobStatus.RUNNING
        job.result_message = "Restore started"
        db.add(job)
        db.commit()

        if not backup_job or backup_job.backup_type.value != "server" or not backup_job.storage_path:
            raise RuntimeError("Backup archive is not available for restore")
        if not job.server_id:
            raise RuntimeError("Restore job requires target server_id")

        server = db.query(Server).filter(Server.id == job.server_id).first()
        if not server:
            raise RuntimeError("Target server not found")

        bundle = asyncio.run(ServerRestoreService().restore_backup(server, Path(backup_job.storage_path), bundle_server_id=bundle_server_id))
        try:
            _refresh_server_live_runtime_state(db, server)
        except Exception:
            pass

        job.status = JobStatus.SUCCEEDED
        job.result_message = bundle.result_message
        db.add(job)
        db.add(server)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.query(DeploymentJob).filter(DeploymentJob.id == job_id).first()
        if job:
            job.status = JobStatus.FAILED
            job.result_message = str(exc)
            db.add(job)
            db.commit()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.restore_panel_backup")
def restore_panel_backup(job_id: int) -> None:
    db: Session = SessionLocal()
    backup_job_id: int | None = None
    try:
        job = db.query(DeploymentJob).filter(DeploymentJob.id == job_id).first()
        if not job:
            return
        if job.result_message and job.result_message.startswith("RestoreBackupJob:"):
            backup_job_id = int(job.result_message.split(":", maxsplit=1)[1])
        backup_job = db.query(BackupJob).filter(BackupJob.id == backup_job_id).first() if backup_job_id else None

        job.status = JobStatus.RUNNING
        job.result_message = "Panel restore started"
        db.add(job)
        db.commit()

        if not backup_job or backup_job.backup_type.value != "database" or not backup_job.storage_path:
            raise RuntimeError("Panel backup archive is not available for restore")

        # Close ORM connections before restoring the same PostgreSQL database.
        db.close()
        PanelRestoreService().restore_backup(Path(backup_job.storage_path))
        return
    except Exception as exc:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:
            pass
        try:
            reopened: Session = SessionLocal()
            job = reopened.query(DeploymentJob).filter(DeploymentJob.id == job_id).first()
            if job:
                job.status = JobStatus.FAILED
                job.result_message = str(exc)
                reopened.add(job)
                reopened.commit()
            reopened.close()
        except Exception:
            pass
    finally:
        try:
            db.close()
        except Exception:
            pass


@celery_app.task(name="app.workers.tasks.sync_client_runtime_stats")
def sync_client_runtime_stats() -> None:
    db: Session = SessionLocal()
    service = ClientsTableService()
    client_sync = ClientSyncService()
    server_agent = ServerAgentService()
    try:
        servers = (
            db.query(Server)
            .filter(
                Server.awg_detected.is_(True),
                Server.live_runtime_details_json.is_not(None),
            )
            .all()
        )
        for server in servers:
            clients = db.query(Client).filter(Client.server_id == server.id, Client.archived.is_(False)).all()
            if not clients:
                continue
            agent = db.query(AgentNode).filter(AgentNode.server_id == server.id).first()
            processed_from_agent = False
            existing_clients_table = ""
            if agent is not None:
                if agent.status != "offline":
                    try:
                        policy_snapshot = service.render_policy_snapshot(server, clients)
                        asyncio.run(server_agent.sync_policy_snapshot(server, policy_snapshot))
                        asyncio.run(
                            server_agent.enqueue_local_task(
                                server,
                                "policy-enforcer",
                                "enforce-client-policies",
                                {"repeat": True, "silent": True},
                            )
                        )
                    except Exception:
                        pass

                try:
                    policy_state = asyncio.run(server_agent.fetch_policy_state(server))
                except Exception:
                    policy_state = None
                if isinstance(policy_state, dict):
                    service_updated, _ = service.sync_db_runtime_stats_from_agent_policy_state(db, server, policy_state)
                    if service_updated:
                        db.commit()
                    else:
                        db.rollback()
                    processed_from_agent = True

                _, clients_table_payload = _consume_completed_agent_task(db, agent, server, "read-clients-table")
                if clients_table_payload:
                    existing_clients_table = str(clients_table_payload.get("content") or "").strip()

                _, traffic_payload = _consume_completed_agent_task(db, agent, server, "collect-traffic-counters")
                if traffic_payload:
                    awg_dump = str(traffic_payload.get("awg_dump") or "").strip()
                    if awg_dump:
                        if existing_clients_table:
                            merged_clients_table = asyncio.run(service.merge_runtime_stats(server, existing_clients_table))
                            if merged_clients_table != existing_clients_table:
                                asyncio.run(service.upload(server, merged_clients_table))
                        service_updated, should_apply_server_clients = service.sync_db_runtime_stats_from_dump(db, server, awg_dump)
                        if service_updated or should_apply_server_clients:
                            db.commit()
                            if should_apply_server_clients:
                                client_sync.apply_server_clients(db, server)
                            db.commit()
                        else:
                            db.rollback()
                        processed_from_agent = True

                for task_type in ("read-clients-table", "collect-traffic-counters"):
                    pending_task = (
                        db.query(AgentTask)
                        .filter(
                            AgentTask.agent_id == agent.id,
                            AgentTask.server_id == server.id,
                            AgentTask.task_type == task_type,
                            AgentTask.status.in_(["pending", "running"]),
                        )
                        .order_by(AgentTask.created_at.asc(), AgentTask.id.asc())
                        .first()
                    )
                    if pending_task is None and agent.status != "offline":
                        task = AgentTask(
                            agent_id=agent.id,
                            server_id=server.id,
                            task_type=task_type,
                            status="pending",
                            payload_json=None,
                            requested_by_user_id=None,
                        )
                        db.add(task)
                        db.commit()
                        db.refresh(task)
                        asyncio.run(server_agent.enqueue_local_task(server, str(task.id), task.task_type, None))

            if processed_from_agent:
                continue
            existing_clients_table = asyncio.run(service.fetch_existing(server))
            if existing_clients_table:
                merged_clients_table = asyncio.run(service.merge_runtime_stats(server, existing_clients_table))
                if merged_clients_table != existing_clients_table:
                    asyncio.run(service.upload(server, merged_clients_table))
            service_updated, should_apply_server_clients = asyncio.run(service.sync_db_runtime_stats(db, server))
            if service_updated or should_apply_server_clients:
                db.commit()
                if should_apply_server_clients:
                    client_sync.apply_server_clients(db, server)
            else:
                db.rollback()
    except Exception:  # noqa: BLE001
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.sync_server_runtime_metrics")
def sync_server_runtime_metrics() -> None:
    db: Session = SessionLocal()
    service = ServerMetricsService()
    failover_agent = ProxyFailoverAgentService()
    server_agent = ServerAgentService()
    try:
        servers = db.query(Server).filter(Server.access_status == AccessStatus.OK).all()
        for server in servers:
            try:
                updated = False
                agent_changed = False
                queued_local_task = False
                agent = db.query(AgentNode).filter(AgentNode.server_id == server.id).first()
                if agent is not None:
                    status_payload = None
                    try:
                        status_payload = asyncio.run(server_agent.fetch_local_status(server))
                    except Exception as exc:  # noqa: BLE001
                        agent.status = "offline"
                        agent.last_error = str(exc)
                        db.add(agent)
                        agent_changed = True
                    else:
                        agent_changed = _sync_panel_agent_from_local_status(agent, status_payload) or agent_changed
                        db.add(agent)

                    try:
                        results = asyncio.run(server_agent.fetch_local_results(server))
                    except Exception as exc:  # noqa: BLE001
                        agent.last_error = str(exc)
                        db.add(agent)
                        agent_changed = True
                        results = []

                    if results:
                        now = datetime.now(UTC)
                        for item in results:
                            task_id_raw = item.get("id")
                            if task_id_raw is None:
                                continue
                            try:
                                task_id = int(task_id_raw)
                            except (TypeError, ValueError):
                                continue
                            task = (
                                db.query(AgentTask)
                                .filter(AgentTask.id == task_id, AgentTask.agent_id == agent.id)
                                .first()
                            )
                            if task is None:
                                continue
                            task.status = str(item.get("status") or task.status)
                            result_payload = item.get("result")
                            task.result_json = json.dumps(result_payload, ensure_ascii=False) if result_payload is not None else task.result_json
                            task.last_error = str(item.get("last_error")) if item.get("last_error") else None
                            task.completed_at = now if task.status in {"succeeded", "failed"} else task.completed_at
                            db.add(task)
                            if (
                                task.task_type == "collect-runtime-snapshot"
                                and task.status == "succeeded"
                                and isinstance(result_payload, dict)
                            ):
                                updated = service.sync_server_from_agent_payload(db, server, result_payload) or updated
                        agent.last_sync_at = now
                        db.add(agent)
                        agent_changed = True

                    if agent.status != "offline":
                        local_task = _ensure_local_agent_task(db, server, agent, "collect-runtime-snapshot")
                        if local_task is not None:
                            asyncio.run(server_agent.enqueue_local_task(server, str(local_task.id), local_task.task_type, None))
                            queued_local_task = True

                if agent is None or (not updated and agent is not None and agent.status == "offline"):
                    updated = asyncio.run(service.sync_server(db, server)) or updated

                status_payload = asyncio.run(failover_agent.fetch_status(server))
                status_updated = failover_agent.sync_status_to_db(db, server, status_payload)
                if updated or status_updated or agent_changed or queued_local_task:
                    db.commit()
                else:
                    db.rollback()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                service.mark_collection_error(db, server, exc)
                db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.sync_extra_service_runtime")
def sync_extra_service_runtime() -> None:
    db: Session = SessionLocal()
    try:
        services = db.query(ServiceInstance).filter(ServiceInstance.service_type.in_(["mtproxy", "socks5", "xray"])).all()
        for service in services:
            server = db.query(Server).filter(Server.id == service.server_id).first()
            if not server:
                continue
            try:
                if service.service_type == "mtproxy":
                    _sync_mtproxy_service(db, service, server)
                elif service.service_type == "socks5":
                    _sync_socks5_service(db, service, server)
                else:
                    _sync_xray_service(db, service, server)
                db.commit()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                service = db.query(ServiceInstance).filter(ServiceInstance.id == service.id).first()
                if not service:
                    continue
                service.status = "error"
                service.last_error = str(exc)
                db.add(service)
                db.commit()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.reconcile_stale_jobs")
def reconcile_stale_jobs() -> None:
    db: Session = SessionLocal()
    try:
        now = datetime.now(UTC)
        candidates = (
            db.query(DeploymentJob)
            .filter(DeploymentJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]))
            .all()
        )
        for job in candidates:
            if not job.updated_at:
                continue
            if now - job.updated_at < _stale_job_timeout(job):
                continue
            job.status = JobStatus.FAILED
            job.result_message = (
                f"Job was marked failed by stale-job reconciler after exceeding the timeout for {job.job_type.value}"
            )
            db.add(job)
            if job.topology_id:
                topology = db.query(Topology).filter(Topology.id == job.topology_id).first()
                if topology and topology.status == TopologyStatus.PENDING:
                    topology.status = TopologyStatus.ERROR
                    db.add(topology)
        db.commit()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.run_scheduled_backups")
def run_scheduled_backups() -> None:
    db: Session = SessionLocal()
    try:
        service = AppSettingsService()
        backup_settings = service.get_backup_settings(db)
        now = datetime.now(UTC)
        if not backup_settings.auto_backup_enabled or now.hour != backup_settings.auto_backup_hour_utc:
            return

        today_key = now.date().isoformat()
        last_auto_backup_date = service.get_raw_backup_marker(db, "last_auto_backup_date")
        if last_auto_backup_date == today_key:
            return

        backup_job = BackupJob(
            backup_type=BackupType.DATABASE,
            status=BackupStatus.PENDING,
        )
        db.add(backup_job)
        db.commit()
        db.refresh(backup_job)

        deployment_job = DeploymentJob(
            job_type=JobType.BACKUP,
            status=JobStatus.PENDING,
            result_message=f"BackupJob:{backup_job.id}",
        )
        db.add(deployment_job)
        db.commit()
        db.refresh(deployment_job)
        deployment_job.task_id = JobService().dispatch_job(deployment_job)
        db.add(deployment_job)
        db.commit()

        service.set_raw_backup_marker(db, "last_auto_backup_date", today_key)
    except Exception:
        db.rollback()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.cleanup_old_backups")
def cleanup_old_backups() -> None:
    db: Session = SessionLocal()
    try:
        service = AppSettingsService()
        backup_settings = service.get_backup_settings(db)
        now = datetime.now(UTC)
        today_key = now.date().isoformat()
        last_cleanup_date = service.get_raw_backup_marker(db, "last_backup_cleanup_date")
        if last_cleanup_date == today_key:
            return

        cutoff = now - timedelta(days=backup_settings.backup_retention_days)
        old_backups = (
            db.query(BackupJob)
            .filter(
                BackupJob.storage_path.is_not(None),
                BackupJob.created_at < cutoff,
            )
            .all()
        )
        for backup_job in old_backups:
            archive_path = Path(backup_job.storage_path or "")
            if archive_path.exists():
                try:
                    archive_path.unlink()
                except Exception:
                    continue
            backup_job.storage_path = None
            existing_message = (backup_job.result_message or "").strip()
            backup_job.result_message = (existing_message + " | " if existing_message else "") + "Archive expired and removed by retention policy"
            db.add(backup_job)
        db.commit()
        service.set_raw_backup_marker(db, "last_backup_cleanup_date", today_key)
    except Exception:
        db.rollback()
    finally:
        db.close()
