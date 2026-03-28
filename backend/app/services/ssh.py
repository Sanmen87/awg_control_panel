from __future__ import annotations

import asyncio
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
        connect_timeout_seconds: float = 15.0,
    ) -> asyncssh.SSHClientConnection:
        connect_kwargs: dict[str, object] = {
            "host": host,
            "username": username,
            "port": port,
            "known_hosts": None,
            "connect_timeout": connect_timeout_seconds,
        }
        if password:
            connect_kwargs["password"] = password

        if private_key:
            with tempfile.NamedTemporaryFile("w", delete=False) as key_file:
                key_file.write(private_key)
                key_path = key_file.name
            connect_kwargs["client_keys"] = [key_path]
            try:
                try:
                    return await asyncssh.connect(**connect_kwargs)
                except TimeoutError as exc:
                    raise TimeoutError(
                        f"SSH connect timed out after {int(connect_timeout_seconds)}s to {host}:{port}"
                    ) from exc
            finally:
                os.unlink(key_path)

        try:
            return await asyncssh.connect(**connect_kwargs)
        except TimeoutError as exc:
            raise TimeoutError(
                f"SSH connect timed out after {int(connect_timeout_seconds)}s to {host}:{port}"
            ) from exc

    async def run_command(
        self,
        *,
        host: str,
        username: str,
        command: str,
        port: int = 22,
        password: str | None = None,
        private_key: str | None = None,
        timeout_seconds: float = 120.0,
        connect_timeout_seconds: float = 15.0,
    ) -> SSHCommandResult:
        async with await self._connect(
            host=host,
            username=username,
            port=port,
            password=password,
            private_key=private_key,
            connect_timeout_seconds=connect_timeout_seconds,
        ) as conn:
            try:
                result = await asyncio.wait_for(conn.run(command, check=False), timeout=timeout_seconds)
            except TimeoutError as exc:
                raise TimeoutError(f"SSH command timed out after {int(timeout_seconds)}s on {host}") from exc
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
        connect_timeout_seconds: float = 15.0,
    ) -> None:
        async with await self._connect(
            host=host,
            username=username,
            port=port,
            password=password,
            private_key=private_key,
            connect_timeout_seconds=connect_timeout_seconds,
        ) as conn:
            async with conn.start_sftp_client() as sftp:
                async with sftp.open(remote_path, "w") as remote_file:
                    await remote_file.write(content)
