from __future__ import annotations

import io
import json
import os
import re
import subprocess
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings


@dataclass
class PanelBackupBundle:
    archive_path: Path
    result_message: str


class PanelBackupService:
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

    def _dump_database(self) -> str:
        env = os.environ.copy()
        env["PGPASSWORD"] = settings.postgres_password
        command = [
            "pg_dump",
            "-h",
            settings.postgres_host,
            "-p",
            str(settings.postgres_port),
            "-U",
            settings.postgres_user,
            "-d",
            settings.postgres_db,
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
        ]
        result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "pg_dump failed")
        return result.stdout

    def create_backup(self, backup_job_id: int, target_dir: Path) -> PanelBackupBundle:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        archive_name = f"{self._slugify(settings.project_name, 'awg-control-panel')}-panel-backup-{backup_job_id}-{timestamp}.tar.gz"
        archive_path = target_dir / archive_name
        db_dump = self._dump_database()
        manifest = {
            "version": 1,
            "created_at": timestamp,
            "backup_type": "database",
            "panel": {
                "project_name": settings.project_name,
                "environment": settings.environment,
                "postgres_db": settings.postgres_db,
                "postgres_host": settings.postgres_host,
                "postgres_port": settings.postgres_port,
            },
        }

        target_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "w:gz") as archive:
            self._add_text(archive, "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            self._add_text(archive, "panel/postgres.sql", db_dump)

        return PanelBackupBundle(
            archive_path=archive_path,
            result_message=f"Panel backup completed: {archive_path}",
        )
