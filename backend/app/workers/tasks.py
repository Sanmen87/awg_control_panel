import asyncio
import json
import re
from pathlib import Path
import tarfile
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.backup import BackupJob, BackupStatus
from app.models.client import Client
from app.db.session import SessionLocal
from app.models.job import DeploymentJob, JobStatus, JobType
from app.models.server import AWGStatus, AccessStatus, InstallMethod, Server, ServerStatus
from app.models.topology import Topology, TopologyStatus, TopologyType
from app.models.topology_node import TopologyNode
from app.services.awg_detection import DETECT_AWG_COMMAND, parse_detection_output
from app.services.awg_profile import AWGProfileService
from app.services.bootstrap_commands import (
    BOOTSTRAP_SERVER_DOCKER_COMMAND,
    BOOTSTRAP_SERVER_GO_COMMAND,
    CHECK_SERVER_COMMAND,
    wrap_with_optional_sudo,
)
from app.services.client_sync import ClientSyncService
from app.services.server_credentials import ServerCredentialsService
from app.services.clients_table import ClientsTableService
from app.services.server_metrics import ServerMetricsService
from app.services.ssh import SSHService
from app.services.standard_config_inspector import StandardConfigInspector
from app.services.topology_deployer import deploy_topology_sync
from app.services.topology_renderer import TopologyRenderer
from app.workers.celery_app import celery_app


def _extract_rendered_config_value(content: str, key: str) -> str | None:
    pattern = rf"^{re.escape(key)}\s*=\s*(.+)$"
    match = re.search(pattern, content, re.MULTILINE)
    return match.group(1).strip() if match else None


def _persist_generated_standard_server_state(db: Session, topology: Topology | None, rendered_files: list) -> None:
    if not topology or topology.type not in {TopologyType.STANDARD, TopologyType.PROXY_EXIT}:
        return
    profile_service = AWGProfileService()
    for rendered in rendered_files:
        server = db.query(Server).filter(Server.id == rendered.server_id).first()
        if not server:
            continue
        if rendered.metadata and rendered.metadata.get("preserve_server_runtime") == "1":
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
    # Current backup task creates an application archive placeholder; DB dump/export comes next.
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

        backup_dir = Path("/app/backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        archive_path = backup_dir / f"backup-job-{backup_job_id or job_id}-{timestamp}.tar.gz"

        with tarfile.open(archive_path, "w:gz") as archive:
            for candidate in [Path("/app/alembic.ini"), Path("/app/app")]:
                if candidate.exists():
                    archive.add(candidate, arcname=candidate.name)

        job.status = JobStatus.SUCCEEDED
        job.result_message = f"Backup completed: {archive_path}"
        db.add(job)

        if backup_job:
            backup_job.status = BackupStatus.SUCCEEDED
            backup_job.storage_path = str(archive_path)
            backup_job.result_message = "Backup archive created"
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


@celery_app.task(name="app.workers.tasks.sync_client_runtime_stats")
def sync_client_runtime_stats() -> None:
    db: Session = SessionLocal()
    service = ClientsTableService()
    client_sync = ClientSyncService()
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
    try:
        servers = db.query(Server).filter(Server.access_status == AccessStatus.OK).all()
        for server in servers:
            try:
                updated = asyncio.run(service.sync_server(db, server))
                if updated:
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
