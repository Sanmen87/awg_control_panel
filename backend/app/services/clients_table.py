from __future__ import annotations

import json
import re
import shlex
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.client_runtime_sample import ClientRuntimeSample
from app.models.server import Server
from app.services.bootstrap_commands import wrap_with_optional_sudo
from app.services.server_runtime_paths import (
    build_read_clients_table_command,
    build_show_dump_command,
    get_docker_container,
    get_primary_clients_table_path,
    parse_runtime_details,
)
from app.services.server_credentials import ServerCredentialsService
from app.services.ssh import SSHService


class ClientsTableService:
    def __init__(self) -> None:
        self.ssh = SSHService()
        self.credentials = ServerCredentialsService()

    def render(self, clients: list[Client], existing_raw_table: str | None = None) -> str:
        preserved_by_public_key = self._parse_existing_table(existing_raw_table or "")
        payload: list[dict[str, object]] = []
        for client in clients:
            if not client.public_key:
                continue
            existing = preserved_by_public_key.get(client.public_key, {})
            user_data = {
                "clientName": client.name,
            }
            if client.assigned_ip:
                user_data["allowedIps"] = client.assigned_ip

            creation_date = existing.get("creationDate") or self._format_creation_date(client)
            if creation_date:
                user_data["creationDate"] = creation_date

            for key in ["dataReceived", "dataSent", "latestHandshake"]:
                value = existing.get(key)
                if value:
                    user_data[key] = value

            payload.append(
                {
                    "clientId": client.public_key,
                    "userData": user_data,
                }
            )
        return json.dumps(payload, ensure_ascii=False, indent=4)

    def render_policy_snapshot(self, server: Server, clients: list[Client]) -> str:
        runtime_details = parse_runtime_details(server)
        payload = {
            "version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "server_id": server.id,
            "runtime": {
                "runtime": server.runtime_flavor or runtime_details.get("runtime") or "",
                "interface_name": server.live_interface_name or runtime_details.get("interface") or "awg0",
                "config_path": server.live_config_path or runtime_details.get("config_path") or "",
                "docker_container": get_docker_container(server, runtime_details) or "",
            },
            "clients": [
                {
                    "id": client.id,
                    "name": client.name,
                    "public_key": client.public_key,
                    "assigned_ip": client.assigned_ip,
                    "manual_disabled": client.manual_disabled,
                    "expires_at": client.expires_at.isoformat() if client.expires_at else None,
                    "quiet_hours_start_minute": client.quiet_hours_start_minute,
                    "quiet_hours_end_minute": client.quiet_hours_end_minute,
                    "quiet_hours_timezone": client.quiet_hours_timezone,
                    "traffic_limit_mb": client.traffic_limit_mb,
                }
                for client in clients
                if client.public_key and client.assigned_ip and not client.archived
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    async def fetch_existing(self, server: Server) -> str:
        runtime_details = parse_runtime_details(server)
        command = build_read_clients_table_command(server, runtime_details)
        if not get_docker_container(server, runtime_details):
            command = wrap_with_optional_sudo(command, self.credentials.get_sudo_password(server))

        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=self.credentials.get_ssh_password(server),
            private_key=self.credentials.get_private_key(server),
            command=command,
        )
        if result.exit_status != 0:
            return ""
        return result.stdout.strip()

    async def merge_runtime_stats(self, server: Server, existing_raw_table: str) -> str:
        stats_by_public_key = await self._fetch_runtime_stats(server)
        if not stats_by_public_key:
            return existing_raw_table
        try:
            payload = json.loads(existing_raw_table)
        except json.JSONDecodeError:
            return existing_raw_table
        if not isinstance(payload, list):
            return existing_raw_table

        updated = False
        for item in payload:
            if not isinstance(item, dict):
                continue
            client_id = str(item.get("clientId", "")).strip()
            user_data = item.get("userData")
            if not client_id or not isinstance(user_data, dict):
                continue
            stats = stats_by_public_key.get(client_id)
            if not stats:
                continue
            if stats.get("allowedIps"):
                user_data["allowedIps"] = str(stats["allowedIps"])
            if stats.get("latestHandshakeHuman"):
                user_data["latestHandshake"] = str(stats["latestHandshakeHuman"])
            if stats.get("dataReceivedHuman"):
                user_data["dataReceived"] = str(stats["dataReceivedHuman"])
            if stats.get("dataSentHuman"):
                user_data["dataSent"] = str(stats["dataSentHuman"])
            updated = True
        if not updated:
            return existing_raw_table
        return json.dumps(payload, ensure_ascii=False, indent=4)

    async def sync_db_runtime_stats(self, db: Session, server: Server) -> tuple[int, bool]:
        stats_by_public_key = await self._fetch_runtime_stats(server)
        return self.sync_db_runtime_stats_from_parsed_stats(db, server, stats_by_public_key)

    def sync_db_runtime_stats_from_dump(self, db: Session, server: Server, output: str) -> tuple[int, bool]:
        return self.sync_db_runtime_stats_from_parsed_stats(db, server, self._parse_show_dump_output(output))

    def sync_db_runtime_stats_from_parsed_stats(
        self,
        db: Session,
        server: Server,
        stats_by_public_key: dict[str, dict[str, str | int]],
    ) -> tuple[int, bool]:
        refreshed_at = datetime.now(UTC)
        rolling_cutoff = refreshed_at - timedelta(days=30)
        clients = db.query(Client).filter(Client.server_id == server.id, Client.archived.is_(False)).all()
        updated_count = 0
        should_apply_server_clients = False

        for client in clients:
            stats = stats_by_public_key.get(client.public_key or "")
            connected = self._is_connected(stats, refreshed_at)
            latest_handshake_human = str(stats.get("latestHandshakeHuman")) if stats and stats.get("latestHandshakeHuman") else None
            data_received_human = str(stats.get("dataReceivedHuman")) if stats and stats.get("dataReceivedHuman") else None
            data_sent_human = str(stats.get("dataSentHuman")) if stats and stats.get("dataSentHuman") else None

            if stats:
                previous_sample = (
                    db.query(ClientRuntimeSample)
                    .filter(ClientRuntimeSample.client_id == client.id)
                    .order_by(ClientRuntimeSample.sampled_at.desc(), ClientRuntimeSample.id.desc())
                    .first()
                )
                rx_total = int(stats.get("rxBytesTotal") or 0)
                tx_total = int(stats.get("txBytesTotal") or 0)

                if previous_sample is None:
                    rx_delta = 0
                    tx_delta = 0
                else:
                    rx_delta = rx_total - previous_sample.rx_bytes_total
                    tx_delta = tx_total - previous_sample.tx_bytes_total
                    if rx_delta < 0:
                        rx_delta = rx_total
                    if tx_delta < 0:
                        tx_delta = tx_total

                db.add(
                    ClientRuntimeSample(
                        client_id=client.id,
                        server_id=server.id,
                        sampled_at=refreshed_at,
                        latest_handshake_at=self._timestamp_to_datetime(stats.get("latestHandshakeAt")),
                        is_connected=connected,
                        rx_bytes_total=rx_total,
                        tx_bytes_total=tx_total,
                        rx_bytes_delta=rx_delta,
                        tx_bytes_delta=tx_delta,
                    )
                )

            rolling_rx = int(
                db.query(func.coalesce(func.sum(ClientRuntimeSample.rx_bytes_delta), 0))
                .filter(
                    ClientRuntimeSample.client_id == client.id,
                    ClientRuntimeSample.sampled_at >= rolling_cutoff,
                )
                .scalar()
                or 0
            )
            rolling_tx = int(
                db.query(func.coalesce(func.sum(ClientRuntimeSample.tx_bytes_delta), 0))
                .filter(
                    ClientRuntimeSample.client_id == client.id,
                    ClientRuntimeSample.sampled_at >= rolling_cutoff,
                )
                .scalar()
                or 0
            )

            limit_bytes = (client.traffic_limit_mb or 0) * 1024 * 1024 if client.traffic_limit_mb else None
            limit_exceeded = bool(limit_bytes and (rolling_rx + rolling_tx) > limit_bytes)
            policy_reason = self._resolve_policy_disabled_reason(client, refreshed_at, limit_exceeded)

            if (
                client.runtime_connected != connected
                or client.latest_handshake_human != latest_handshake_human
                or client.data_received_human != data_received_human
                or client.data_sent_human != data_sent_human
                or client.traffic_used_30d_rx_bytes != rolling_rx
                or client.traffic_used_30d_tx_bytes != rolling_tx
                or client.policy_disabled_reason != policy_reason
            ):
                updated_count += 1

            client.runtime_connected = connected
            client.latest_handshake_human = latest_handshake_human
            client.data_received_human = data_received_human
            client.data_sent_human = data_sent_human
            client.traffic_used_30d_rx_bytes = rolling_rx
            client.traffic_used_30d_tx_bytes = rolling_tx
            client.runtime_refreshed_at = refreshed_at

            if limit_exceeded and client.traffic_limit_exceeded_at is None:
                client.traffic_limit_exceeded_at = refreshed_at
            elif not limit_exceeded:
                client.traffic_limit_exceeded_at = None

            previous_policy_reason = client.policy_disabled_reason
            if policy_reason:
                client.policy_disabled_reason = policy_reason
            elif previous_policy_reason in {"traffic_limit", "quiet_hours", "expired"}:
                client.policy_disabled_reason = None

            if policy_reason and client.status == "active":
                client.status = "disabled"
                should_apply_server_clients = True
            elif (
                not policy_reason
                and previous_policy_reason in {"traffic_limit", "quiet_hours", "expired"}
                and not client.manual_disabled
                and client.status == "disabled"
            ):
                client.status = "active"
                should_apply_server_clients = True

            db.add(client)

        self._prune_old_samples(db, refreshed_at - timedelta(days=45), server.id)
        return updated_count, should_apply_server_clients

    def sync_db_runtime_stats_from_agent_policy_state(
        self,
        db: Session,
        server: Server,
        payload: dict[str, object],
    ) -> tuple[int, bool]:
        collected_at_raw = payload.get("collected_at")
        try:
            refreshed_at = datetime.fromisoformat(str(collected_at_raw)) if collected_at_raw else datetime.now(UTC)
        except ValueError:
            refreshed_at = datetime.now(UTC)
        if refreshed_at.tzinfo is None:
            refreshed_at = refreshed_at.replace(tzinfo=UTC)

        clients_payload = payload.get("clients")
        if not isinstance(clients_payload, dict):
            return 0, False

        updated_count = 0
        clients = db.query(Client).filter(Client.server_id == server.id, Client.archived.is_(False)).all()
        for client in clients:
            state = clients_payload.get(client.public_key or "")
            if not isinstance(state, dict):
                continue

            rx_total = self._safe_int(state.get("rx_total"))
            tx_total = self._safe_int(state.get("tx_total"))
            rolling_rx = self._safe_int(state.get("rolling_rx"))
            rolling_tx = self._safe_int(state.get("rolling_tx"))
            runtime_connected = bool(state.get("runtime_connected"))
            latest_handshake_human = str(state.get("latest_handshake_human") or "") or None
            data_received_human = str(state.get("data_received_human") or "") or None
            data_sent_human = str(state.get("data_sent_human") or "") or None
            policy_reason = str(state.get("policy_disabled_reason") or "") or None
            manual_disabled = bool(state.get("manual_disabled"))
            latest_handshake_at = self._timestamp_to_datetime(state.get("latest_handshake_at"))

            previous_sample = (
                db.query(ClientRuntimeSample)
                .filter(ClientRuntimeSample.client_id == client.id)
                .order_by(ClientRuntimeSample.sampled_at.desc(), ClientRuntimeSample.id.desc())
                .first()
            )
            should_add_sample = previous_sample is None or previous_sample.sampled_at < refreshed_at
            if should_add_sample:
                if previous_sample is None:
                    rx_delta = 0
                    tx_delta = 0
                else:
                    rx_delta = rx_total - previous_sample.rx_bytes_total
                    tx_delta = tx_total - previous_sample.tx_bytes_total
                    if rx_delta < 0:
                        rx_delta = rx_total
                    if tx_delta < 0:
                        tx_delta = tx_total
                db.add(
                    ClientRuntimeSample(
                        client_id=client.id,
                        server_id=server.id,
                        sampled_at=refreshed_at,
                        latest_handshake_at=latest_handshake_at,
                        is_connected=runtime_connected,
                        rx_bytes_total=rx_total,
                        tx_bytes_total=tx_total,
                        rx_bytes_delta=rx_delta,
                        tx_bytes_delta=tx_delta,
                    )
                )

            if (
                client.runtime_connected != runtime_connected
                or client.latest_handshake_human != latest_handshake_human
                or client.data_received_human != data_received_human
                or client.data_sent_human != data_sent_human
                or client.traffic_used_30d_rx_bytes != rolling_rx
                or client.traffic_used_30d_tx_bytes != rolling_tx
                or client.policy_disabled_reason != policy_reason
                or client.manual_disabled != manual_disabled
            ):
                updated_count += 1

            client.runtime_connected = runtime_connected
            client.latest_handshake_human = latest_handshake_human
            client.data_received_human = data_received_human
            client.data_sent_human = data_sent_human
            client.traffic_used_30d_rx_bytes = rolling_rx
            client.traffic_used_30d_tx_bytes = rolling_tx
            client.runtime_refreshed_at = refreshed_at
            client.manual_disabled = manual_disabled
            client.policy_disabled_reason = policy_reason

            if policy_reason == "traffic_limit" and client.traffic_limit_exceeded_at is None:
                client.traffic_limit_exceeded_at = refreshed_at
            elif policy_reason != "traffic_limit":
                client.traffic_limit_exceeded_at = None

            effective_disabled = manual_disabled or bool(policy_reason)
            if effective_disabled and client.status == "active":
                client.status = "disabled"
            elif not effective_disabled and client.status == "disabled":
                client.status = "active"

            db.add(client)

        self._prune_old_samples(db, refreshed_at - timedelta(days=45), server.id)
        return updated_count, False

    async def upload(self, server: Server, content: str) -> None:
        password = self.credentials.get_ssh_password(server)
        private_key = self.credentials.get_private_key(server)
        sudo_password = self.credentials.get_sudo_password(server)
        runtime_details = parse_runtime_details(server)
        docker_container = get_docker_container(server, runtime_details)
        remote_path = get_primary_clients_table_path(server, runtime_details)
        temp_remote = "/tmp/clientsTable"

        await self.ssh.upload_text_file(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            remote_path=temp_remote,
            content=content,
        )

        if docker_container:
            command = (
                "set -e && "
                f"docker cp {shlex.quote(temp_remote)} {shlex.quote(docker_container)}:{shlex.quote(remote_path)} && "
                f"docker exec {shlex.quote(docker_container)} sh -lc 'chmod 600 {shlex.quote(remote_path)} 2>/dev/null || true' && "
                f"rm -f {shlex.quote(temp_remote)}"
            )
        else:
            remote_dir = remote_path.rsplit("/", 1)[0] if "/" in remote_path else "/etc/amnezia/amneziawg"
            command = wrap_with_optional_sudo(
                "set -e && "
                f"mkdir -p {shlex.quote(remote_dir)} && "
                f"mv {shlex.quote(temp_remote)} {shlex.quote(remote_path)} && "
                f"chmod 600 {shlex.quote(remote_path)}",
                sudo_password,
            )

        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            command=command,
        )
        if result.exit_status != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to upload clientsTable")

    def _parse_existing_table(self, raw_table: str) -> dict[str, dict[str, str]]:
        if not raw_table:
            return {}
        try:
            payload = json.loads(raw_table)
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, list):
            return {}

        result: dict[str, dict[str, str]] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            client_id = str(item.get("clientId", "")).strip()
            user_data = item.get("userData") if isinstance(item.get("userData"), dict) else {}
            if not client_id:
                continue
            result[client_id] = {
                "clientName": str(user_data.get("clientName", "")).strip(),
                "allowedIps": str(user_data.get("allowedIps", "")).strip(),
                "creationDate": str(user_data.get("creationDate", "")).strip(),
                "dataReceived": str(user_data.get("dataReceived", "")).strip(),
                "dataSent": str(user_data.get("dataSent", "")).strip(),
                "latestHandshake": str(user_data.get("latestHandshake", "")).strip(),
            }
        return result

    async def _fetch_runtime_stats(self, server: Server) -> dict[str, dict[str, str | int]]:
        runtime_details = parse_runtime_details(server)
        command = build_show_dump_command(server, runtime_details)
        if not get_docker_container(server, runtime_details):
            command = wrap_with_optional_sudo(command, self.credentials.get_sudo_password(server))

        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=self.credentials.get_ssh_password(server),
            private_key=self.credentials.get_private_key(server),
            command=command,
        )
        if result.exit_status != 0:
            return {}
        return self._parse_show_dump_output(result.stdout)

    def _parse_show_dump_output(self, output: str) -> dict[str, dict[str, str | int]]:
        stats_by_public_key: dict[str, dict[str, str | int]] = {}
        if not output.strip():
            return stats_by_public_key

        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            parts = line.split("\t")
            if len(parts) < 8:
                parts = re.split(r"\s+", line)
            if len(parts) == 5:
                continue
            if len(parts) < 9:
                continue

            # `wg show all dump` peer line format:
            # interface public_key preshared_key endpoint allowed_ips latest_handshake rx_bytes tx_bytes keepalive
            peer_key = parts[1].strip()
            if not peer_key:
                continue

            allowed_ips = parts[4].strip()
            latest_handshake_at = self._safe_int(parts[5])
            rx_total = self._safe_int(parts[6])
            tx_total = self._safe_int(parts[7])

            stats_by_public_key[peer_key] = {
                "allowedIps": allowed_ips,
                "latestHandshakeAt": latest_handshake_at,
                "latestHandshakeHuman": self._format_handshake_human(latest_handshake_at),
                "rxBytesTotal": rx_total,
                "txBytesTotal": tx_total,
                "dataReceivedHuman": self._format_bytes_human(rx_total),
                "dataSentHuman": self._format_bytes_human(tx_total),
            }
        return stats_by_public_key

    def _safe_int(self, value: object) -> int:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return 0

    def _format_bytes_human(self, value: int) -> str:
        units = ["B", "KiB", "MiB", "GiB", "TiB"]
        size = float(max(value, 0))
        unit_index = 0
        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1
        if unit_index == 0:
            return f"{int(size)} {units[unit_index]}"
        return f"{size:.2f} {units[unit_index]}"

    def _format_handshake_human(self, latest_handshake_at: int) -> str:
        if latest_handshake_at <= 0:
            return ""
        delta = datetime.now(UTC) - datetime.fromtimestamp(latest_handshake_at, UTC)
        total_seconds = max(int(delta.total_seconds()), 0)
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        parts: list[str] = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds or not parts:
            parts.append(f"{seconds}s")
        return ", ".join(parts[:3]) + " ago"

    def _is_connected(self, stats: dict[str, str | int] | None, now: datetime) -> bool:
        if not stats:
            return False
        latest_handshake_at = self._safe_int(stats.get("latestHandshakeAt"))
        if latest_handshake_at <= 0:
            return False
        latest_handshake_dt = datetime.fromtimestamp(latest_handshake_at, UTC)
        return (now - latest_handshake_dt) <= timedelta(minutes=3)

    def _timestamp_to_datetime(self, value: object) -> datetime | None:
        timestamp = self._safe_int(value)
        if timestamp <= 0:
            return None
        return datetime.fromtimestamp(timestamp, UTC)

    def _resolve_policy_disabled_reason(self, client: Client, now: datetime, limit_exceeded: bool) -> str | None:
        if limit_exceeded:
            return "traffic_limit"
        if client.expires_at:
            expires_at = client.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if now >= expires_at.astimezone(UTC):
                return "expired"
        if self._is_within_quiet_hours(client, now):
            return "quiet_hours"
        return None

    def _is_within_quiet_hours(self, client: Client, now: datetime) -> bool:
        if client.quiet_hours_start_minute is None or client.quiet_hours_end_minute is None:
            return False
        timezone_name = client.quiet_hours_timezone or "UTC"
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            timezone = UTC
        local_now = now.astimezone(timezone)
        current_minute = local_now.hour * 60 + local_now.minute
        start_minute = client.quiet_hours_start_minute
        end_minute = client.quiet_hours_end_minute
        if start_minute == end_minute:
            return True
        if start_minute < end_minute:
            return start_minute <= current_minute < end_minute
        return current_minute >= start_minute or current_minute < end_minute

    def _prune_old_samples(self, db: Session, cutoff: datetime, server_id: int) -> None:
        (
            db.query(ClientRuntimeSample)
            .filter(
                ClientRuntimeSample.server_id == server_id,
                ClientRuntimeSample.sampled_at < cutoff,
            )
            .delete(synchronize_session=False)
        )

    def _format_creation_date(self, client: Client) -> str:
        created_at = getattr(client, "created_at", None)
        if not created_at:
            return ""
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return created_at.astimezone(UTC).strftime("%a %b %d %H:%M:%S %Y")
