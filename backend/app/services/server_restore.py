from __future__ import annotations

import asyncio
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path
from shlex import quote

from app.models.server import Server
from app.services.bootstrap_commands import wrap_with_optional_sudo
from app.services.server_credentials import ServerCredentialsService
from app.services.server_runtime_paths import (
    get_config_path,
    get_docker_container,
    get_primary_clients_table_path,
    parse_runtime_details,
)
from app.services.ssh import SSHService


@dataclass
class ServerRestoreBundle:
    result_message: str


class ServerRestoreService:
    def __init__(self) -> None:
        self.ssh = SSHService()
        self.credentials = ServerCredentialsService()

    def _read_archive(self, archive_path: Path, bundle_server_id: int | None = None) -> tuple[dict[str, object], str, str | None]:
        with tarfile.open(archive_path, "r:gz") as archive:
            manifest_member = archive.getmember("manifest.json")
            manifest = json.loads(archive.extractfile(manifest_member).read().decode("utf-8"))
            backup_type = manifest.get("backup_type")
            if backup_type == "full":
                if bundle_server_id is None:
                    raise RuntimeError("Full bundle restore requires bundle_server_id")
                server_prefix = f"servers/{bundle_server_id}"
                config_member = archive.getmember(f"{server_prefix}/config.conf")
                clients_table_member = next((item for item in archive.getmembers() if item.name == f"{server_prefix}/clientsTable"), None)
            else:
                config_member = archive.getmember("server/config.conf")
                clients_table_member = next((item for item in archive.getmembers() if item.name == "server/clientsTable"), None)
            config_content = archive.extractfile(config_member).read().decode("utf-8")
            clients_table_content = (
                archive.extractfile(clients_table_member).read().decode("utf-8")
                if clients_table_member and archive.extractfile(clients_table_member)
                else None
            )
        if not isinstance(manifest, dict):
            raise RuntimeError("Backup manifest is invalid")
        return manifest, config_content, clients_table_content

    async def restore_backup(self, server: Server, archive_path: Path, bundle_server_id: int | None = None) -> ServerRestoreBundle:
        manifest, config_content, clients_table_content = self._read_archive(archive_path, bundle_server_id=bundle_server_id)
        runtime_details = parse_runtime_details(server)
        manifest_runtime_details = manifest.get("runtime_details") if isinstance(manifest.get("runtime_details"), dict) else {}
        effective_runtime = runtime_details or manifest_runtime_details

        docker_container = get_docker_container(server, effective_runtime)
        config_path = get_config_path(server, effective_runtime)
        if not config_path:
            files_payload = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
            config_path = files_payload.get("config_path") if isinstance(files_payload.get("config_path"), str) else None
        if not config_path:
            raise RuntimeError("Restore requires a target config path")

        interface_name = server.live_interface_name or Path(config_path).stem
        clients_table_path = get_primary_clients_table_path(server, effective_runtime)
        if isinstance(manifest.get("files"), dict):
            manifest_clients_table_path = manifest["files"].get("clients_table_path")
            if isinstance(manifest_clients_table_path, str) and manifest_clients_table_path.strip():
                clients_table_path = manifest_clients_table_path.strip()

        password = self.credentials.get_ssh_password(server)
        private_key = self.credentials.get_private_key(server)
        sudo_password = self.credentials.get_sudo_password(server)

        await self.ssh.upload_text_file(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            remote_path="/tmp/server-restore.conf",
            content=config_content,
        )
        if clients_table_content is not None:
            await self.ssh.upload_text_file(
                host=server.host,
                username=server.ssh_user,
                port=server.ssh_port,
                password=password,
                private_key=private_key,
                remote_path="/tmp/server-restore.clientsTable",
                content=clients_table_content,
            )

        if docker_container:
            config_dir = str(Path(config_path).parent)
            restore_steps = [
                f"docker exec {quote(docker_container)} sh -lc 'mkdir -p {quote(config_dir)}'",
                f"docker cp /tmp/server-restore.conf {quote(docker_container)}:{quote(config_path)}",
                f"docker exec {quote(docker_container)} sh -lc 'chmod 600 {quote(config_path)} 2>/dev/null || true'",
            ]
            if clients_table_content is not None:
                restore_steps.extend(
                    [
                        f"docker exec {quote(docker_container)} sh -lc 'mkdir -p {quote(str(Path(clients_table_path).parent))}'",
                        f"docker cp /tmp/server-restore.clientsTable {quote(docker_container)}:{quote(clients_table_path)}",
                        f"docker exec {quote(docker_container)} sh -lc 'chmod 600 {quote(clients_table_path)} 2>/dev/null || true'",
                    ]
                )
            restore_steps.extend(
                [
                    (
                        f"docker exec {quote(docker_container)} sh -lc "
                        f"{quote(f'(awg-quick down {quote(config_path)} || wg-quick down {quote(config_path)} || true) && (awg-quick up {quote(config_path)} || wg-quick up {quote(config_path)})')}"
                    ),
                    "rm -f /tmp/server-restore.conf /tmp/server-restore.clientsTable",
                ]
            )
        else:
            config_dir = str(Path(config_path).parent)
            autostart = (
                f'if command -v systemctl >/dev/null 2>&1; then '
                f'if systemctl list-unit-files 2>/dev/null | grep -Fq "awg-quick@.service"; then '
                f'systemctl enable awg-quick@{quote(interface_name)}.service >/dev/null 2>&1 || true; '
                f'elif systemctl list-unit-files 2>/dev/null | grep -Fq "wg-quick@.service"; then '
                f'systemctl enable wg-quick@{quote(interface_name)}.service >/dev/null 2>&1 || true; '
                f'fi; fi'
            )
            restore_steps = [
                f"mkdir -p {quote(config_dir)}",
                f"mv /tmp/server-restore.conf {quote(config_path)}",
                f"chmod 600 {quote(config_path)}",
            ]
            if clients_table_content is not None:
                restore_steps.extend(
                    [
                        f"mkdir -p {quote(str(Path(clients_table_path).parent))}",
                        f"mv /tmp/server-restore.clientsTable {quote(clients_table_path)}",
                        f"chmod 600 {quote(clients_table_path)}",
                    ]
                )
            restore_steps.extend(
                [
                    f"(awg-quick down {quote(interface_name)} || wg-quick down {quote(interface_name)} || true)",
                    f"(awg-quick up {quote(interface_name)} || wg-quick up {quote(interface_name)})",
                    autostart,
                    "rm -f /tmp/server-restore.clientsTable 2>/dev/null || true",
                ]
            )

        command = wrap_with_optional_sudo(" && ".join(restore_steps), sudo_password)
        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            command=command,
            timeout_seconds=300,
        )
        if result.exit_status != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Server restore failed")

        return ServerRestoreBundle(result_message=f"Server restore completed from {archive_path}")
