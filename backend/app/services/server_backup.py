from __future__ import annotations

import io
import json
import re
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from shlex import quote

from app.models.server import Server
from app.services.server_credentials import ServerCredentialsService
from app.services.server_runtime_paths import (
    build_read_clients_table_command,
    get_config_path,
    get_docker_container,
    get_primary_clients_table_path,
    parse_runtime_details,
)
from app.services.ssh import SSHService


@dataclass
class ServerBackupBundle:
    archive_path: Path
    result_message: str


class ServerBackupService:
    def __init__(self) -> None:
        self.ssh = SSHService()
        self.credentials = ServerCredentialsService()

    async def _run(self, server: Server, command: str, timeout_seconds: float = 120.0) -> str:
        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=self.credentials.get_ssh_password(server),
            private_key=self.credentials.get_private_key(server),
            command=command,
            timeout_seconds=timeout_seconds,
        )
        if result.exit_status != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "SSH command failed during server backup")
        return result.stdout

    async def _read_live_config(self, server: Server, config_path: str, docker_container: str | None) -> str:
        if docker_container:
            command = f"docker exec {quote(docker_container)} sh -lc {quote(f'cat {quote(config_path)}')}"
        else:
            command = f"sh -lc {quote(f'cat {quote(config_path)}')}"
        return await self._run(server, command)

    async def _read_clients_table(self, server: Server) -> str:
        try:
            return await self._run(server, build_read_clients_table_command(server))
        except Exception:
            return ""

    def _add_text(self, archive: tarfile.TarFile, arcname: str, content: str) -> None:
        encoded = content.encode("utf-8")
        info = tarfile.TarInfo(name=arcname)
        info.size = len(encoded)
        info.mtime = datetime.now(UTC).timestamp()
        archive.addfile(info, io.BytesIO(encoded))

    def _slugify(self, value: str | None, fallback: str) -> str:
        if not value:
            return fallback
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
        normalized = normalized.strip("-._")
        return normalized or fallback

    async def create_backup(self, server: Server, backup_job_id: int, target_dir: Path) -> ServerBackupBundle:
        runtime_details = parse_runtime_details(server)
        docker_container = get_docker_container(server, runtime_details)
        config_path = get_config_path(server, runtime_details)
        if not config_path:
            raise RuntimeError("Server backup requires a detected live config path")

        config_content = await self._read_live_config(server, config_path, docker_container)
        clients_table_content = await self._read_clients_table(server)

        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        server_name = self._slugify(server.name, f"server-{server.id}")
        server_host = self._slugify(server.host, "unknown-host")
        archive_path = target_dir / f"{server_name}-{server_host}-backup-{backup_job_id}-{timestamp}.tar.gz"

        manifest = {
            "version": 1,
            "created_at": timestamp,
            "server": {
                "id": server.id,
                "name": server.name,
                "host": server.host,
                "install_method": server.install_method.value,
                "runtime_flavor": server.runtime_flavor,
                "config_source": server.config_source,
                "live_interface_name": server.live_interface_name,
                "live_config_path": config_path,
                "live_address_cidr": server.live_address_cidr,
                "live_listen_port": server.live_listen_port,
                "live_peer_count": server.live_peer_count,
            },
            "runtime_details": runtime_details,
            "files": {
                "config_path": config_path,
                "clients_table_path": get_primary_clients_table_path(server, runtime_details),
                "docker_container": docker_container,
            },
        }

        with tarfile.open(archive_path, "w:gz") as archive:
            self._add_text(archive, "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            self._add_text(archive, "server/config.conf", config_content)
            if clients_table_content.strip():
                self._add_text(archive, "server/clientsTable", clients_table_content)
            self._add_text(
                archive,
                "server/runtime_details.json",
                json.dumps(runtime_details, ensure_ascii=False, indent=2) + "\n",
            )

        return ServerBackupBundle(
            archive_path=archive_path,
            result_message=f"Server backup completed: {archive_path}",
        )
