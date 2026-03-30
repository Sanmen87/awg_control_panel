from __future__ import annotations

import io
import json
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.models.server import Server
from app.services.panel_backup import PanelBackupService
from app.services.server_backup import ServerBackupService
from app.services.server_runtime_paths import (
    get_config_path,
    get_docker_container,
    get_primary_clients_table_path,
    parse_runtime_details,
)


@dataclass
class FullBundleBackupBundle:
    archive_path: Path
    result_message: str


class FullBundleBackupService:
    def __init__(self) -> None:
        self.panel = PanelBackupService()
        self.server_backup = ServerBackupService()

    def _add_text(self, archive: tarfile.TarFile, arcname: str, content: str) -> None:
        encoded = content.encode("utf-8")
        info = tarfile.TarInfo(name=arcname)
        info.size = len(encoded)
        info.mtime = datetime.now(UTC).timestamp()
        archive.addfile(info, io.BytesIO(encoded))

    async def create_backup(self, backup_job_id: int, target_dir: Path, servers: list[Server]) -> FullBundleBackupBundle:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        archive_name = f"{self.panel._slugify(settings.project_name, 'awg-control-panel')}-full-bundle-{backup_job_id}-{timestamp}.tar.gz"
        archive_path = target_dir / archive_name
        panel_dump = self.panel._dump_database()

        manifest_servers: list[dict[str, object]] = []
        server_payloads: list[tuple[Server, str, str, dict[str, object], str | None]] = []

        for server in servers:
            try:
                runtime_details = parse_runtime_details(server)
                docker_container = get_docker_container(server, runtime_details)
                config_path = get_config_path(server, runtime_details)
                if not config_path:
                    continue
                config_content = await self.server_backup._read_live_config(server, config_path, docker_container)
                clients_table_content = await self.server_backup._read_clients_table(server)
                server_manifest = {
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
                    "clients_table_path": get_primary_clients_table_path(server, runtime_details),
                    "docker_container": docker_container,
                }
                manifest_servers.append(server_manifest)
                server_payloads.append((server, config_path, config_content, runtime_details, clients_table_content or None))
            except Exception:
                continue

        manifest = {
            "version": 1,
            "created_at": timestamp,
            "backup_type": "full",
            "panel": {
                "project_name": settings.project_name,
                "environment": settings.environment,
                "postgres_db": settings.postgres_db,
                "postgres_host": settings.postgres_host,
                "postgres_port": settings.postgres_port,
            },
            "servers": manifest_servers,
        }

        target_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "w:gz") as archive:
            self._add_text(archive, "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            self._add_text(archive, "panel/postgres.sql", panel_dump)
            for server, config_path, config_content, runtime_details, clients_table_content in server_payloads:
                server_dir = f"servers/{server.id}"
                self._add_text(archive, f"{server_dir}/config.conf", config_content)
                self._add_text(
                    archive,
                    f"{server_dir}/runtime_details.json",
                    json.dumps(runtime_details, ensure_ascii=False, indent=2) + "\n",
                )
                self._add_text(
                    archive,
                    f"{server_dir}/manifest.json",
                    json.dumps(
                        {
                            "server_id": server.id,
                            "name": server.name,
                            "host": server.host,
                            "config_path": config_path,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ) + "\n",
                )
                if clients_table_content and clients_table_content.strip():
                    self._add_text(archive, f"{server_dir}/clientsTable", clients_table_content)

        return FullBundleBackupBundle(
            archive_path=archive_path,
            result_message=f"Full bundle backup completed: {archive_path}",
        )
