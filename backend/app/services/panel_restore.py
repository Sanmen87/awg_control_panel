from __future__ import annotations

import json
import os
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings


@dataclass
class PanelRestoreBundle:
    result_message: str


class PanelRestoreService:
    def _read_archive(self, archive_path: Path) -> tuple[dict[str, object], str]:
        with tarfile.open(archive_path, "r:gz") as archive:
            manifest_member = archive.getmember("manifest.json")
            sql_member = archive.getmember("panel/postgres.sql")
            manifest = json.loads(archive.extractfile(manifest_member).read().decode("utf-8"))
            sql_content = archive.extractfile(sql_member).read().decode("utf-8")
        if not isinstance(manifest, dict):
            raise RuntimeError("Backup manifest is invalid")
        if manifest.get("backup_type") not in {"database", "full"}:
            raise RuntimeError("Archive does not contain a panel backup")
        return manifest, sql_content

    def restore_backup(self, archive_path: Path) -> PanelRestoreBundle:
        _, sql_content = self._read_archive(archive_path)
        env = os.environ.copy()
        env["PGPASSWORD"] = settings.postgres_password
        command = [
            "psql",
            "-h",
            settings.postgres_host,
            "-p",
            str(settings.postgres_port),
            "-U",
            settings.postgres_user,
            "-d",
            settings.postgres_db,
            "-v",
            "ON_ERROR_STOP=1",
        ]
        result = subprocess.run(command, env=env, input=sql_content, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "psql restore failed")
        return PanelRestoreBundle(result_message=f"Panel restore completed from {archive_path}")
