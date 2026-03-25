from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

import asyncssh


@dataclass
class SSHCommandResult:
    exit_status: int
    stdout: str
    stderr: str


class SSHService:
    async def _connect(
        self,
        *,
        host: str,
        username: str,
        port: int,
        password: str | None,
        private_key: str | None,
    ) -> asyncssh.SSHClientConnection:
        connect_kwargs: dict[str, object] = {
            "host": host,
            "username": username,
            "port": port,
            "known_hosts": None,
        }
        if password:
            connect_kwargs["password"] = password

        if private_key:
            with tempfile.NamedTemporaryFile("w", delete=False) as key_file:
                key_file.write(private_key)
                key_path = key_file.name
            connect_kwargs["client_keys"] = [key_path]
            try:
                return await asyncssh.connect(**connect_kwargs)
            finally:
                os.unlink(key_path)

        return await asyncssh.connect(**connect_kwargs)

    async def run_command(
        self,
        *,
        host: str,
        username: str,
        command: str,
        port: int = 22,
        password: str | None = None,
        private_key: str | None = None,
    ) -> SSHCommandResult:
        async with await self._connect(
            host=host,
            username=username,
            port=port,
            password=password,
            private_key=private_key,
        ) as conn:
            result = await conn.run(command, check=False)
            return SSHCommandResult(
                exit_status=result.exit_status,
                stdout=result.stdout,
                stderr=result.stderr,
            )

    async def upload_text_file(
        self,
        *,
        host: str,
        username: str,
        remote_path: str,
        content: str,
        port: int = 22,
        password: str | None = None,
        private_key: str | None = None,
    ) -> None:
        async with await self._connect(
            host=host,
            username=username,
            port=port,
            password=password,
            private_key=private_key,
        ) as conn:
            async with conn.start_sftp_client() as sftp:
                async with sftp.open(remote_path, "w") as remote_file:
                    await remote_file.write(content)
