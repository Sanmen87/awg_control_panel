from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.client import Client, ClientSource
from app.models.server import Server
from app.services.bootstrap_commands import wrap_with_optional_sudo
from app.services.server_credentials import ServerCredentialsService
from app.services.server_runtime_paths import (
    get_config_path,
    get_docker_container,
    build_read_clients_table_command,
    build_show_dump_command,
    parse_runtime_details,
)
from app.services.ssh import SSHService

IMPORT_PEERS_COMMAND = r"""
set -e
DOCKER_BIN=$(command -v docker || true)
SOURCE_CMD=""

find_container() {
  docker ps -q 2>/dev/null | while read -r cid; do
    [ -n "$cid" ] || continue
    name=$(docker inspect --format '{{.Name}}' "$cid" 2>/dev/null | sed 's#^/##' || true)
    image=$(docker inspect --format '{{.Config.Image}}' "$cid" 2>/dev/null || true)
    mounts=$(docker inspect --format '{{range .Mounts}}{{println .Destination}}{{end}}' "$cid" 2>/dev/null | tr '\n' ' ' || true)
    score=0

    if printf '%s %s' "$name" "$image" | grep -Ei '(awg|wireguard)' >/dev/null; then
      score=$((score + 8))
    fi
    if printf '%s %s' "$name" "$image" | grep -Ei '(dns)' >/dev/null; then
      score=$((score - 6))
    fi
    if printf '%s' "$mounts" | grep -Ei '(/opt/amnezia/awg|/etc/wireguard|/etc/amnezia)' >/dev/null; then
      score=$((score + 5))
    fi
    if docker exec "$name" sh -lc 'test -d /opt/amnezia/awg || test -f /opt/amnezia/awg/wg0.conf || test -f /opt/amnezia/awg/clientsTable' >/dev/null 2>&1; then
      score=$((score + 20))
    fi
    if docker exec "$name" sh -lc 'command -v awg >/dev/null 2>&1 || command -v wg >/dev/null 2>&1' >/dev/null 2>&1; then
      score=$((score + 10))
    fi

    printf '%s|%s\n' "$score" "$name"
  done | sort -t'|' -k1,1nr | head -n1 | cut -d'|' -f2
}

if command -v awg >/dev/null 2>&1; then
  SOURCE_CMD='awg show all dump'
elif command -v wg >/dev/null 2>&1; then
  SOURCE_CMD='wg show all dump'
elif [ -n "$DOCKER_BIN" ]; then
  DOCKER_CONTAINER=$(find_container)
  if [ -n "$DOCKER_CONTAINER" ]; then
    SOURCE_CMD="docker exec \"$DOCKER_CONTAINER\" sh -lc 'if command -v awg >/dev/null 2>&1; then awg show all dump; elif command -v wg >/dev/null 2>&1; then wg show all dump; fi'"
  fi
fi

if [ -z "$SOURCE_CMD" ]; then
  echo ""
  exit 0
fi

eval "$SOURCE_CMD"
""".strip()


@dataclass
class ImportSummary:
    imported_count: int
    updated_count: int
    skipped_count: int
    client_ids: list[int]


class ClientImportService:
    def __init__(self) -> None:
        self.ssh = SSHService()
        self.credentials = ServerCredentialsService()

    async def _run(self, server: Server, command: str) -> str:
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
        return result.stdout

    async def _fetch_clients_table(self, server: Server) -> str:
        runtime_details = parse_runtime_details(server)
        command = build_read_clients_table_command(server, runtime_details)
        if not get_docker_container(server, runtime_details):
            command = wrap_with_optional_sudo(command, self.credentials.get_sudo_password(server))
        return (await self._run(server, command)).strip()

    async def _fetch_config_text(self, server: Server) -> str:
        runtime_details = parse_runtime_details(server)
        config_path = get_config_path(server, runtime_details)
        if not config_path:
            return ""
        docker_container = get_docker_container(server, runtime_details)
        if docker_container:
            command = (
                f"docker exec {shlex.quote(docker_container)} sh -lc "
                f"{shlex.quote(f'cat {shlex.quote(config_path)} 2>/dev/null || true')}"
            )
        else:
            command = f"sh -lc {shlex.quote(f'cat {shlex.quote(config_path)} 2>/dev/null || true')}"
            command = wrap_with_optional_sudo(command, self.credentials.get_sudo_password(server))
        return (await self._run(server, command)).strip()

    def _normalize_clients_table_records(self, raw_table: str) -> list[dict[str, str]]:
        if not raw_table:
            return []
        try:
            payload = json.loads(raw_table)
        except json.JSONDecodeError:
            payload = None

        if isinstance(payload, list):
            normalized_records: list[dict[str, str]] = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                user_data = item.get("userData") if isinstance(item.get("userData"), dict) else {}
                normalized_records.append(
                    {
                        "public_key": str(item.get("clientId", "")).strip(),
                        "client_name": str(user_data.get("clientName", "")).strip(),
                        "allowed_ips": str(user_data.get("allowedIps", "")).strip(),
                        "creation_date": str(user_data.get("creationDate", "")).strip(),
                        "data_received": str(user_data.get("dataReceived", "")).strip(),
                        "data_sent": str(user_data.get("dataSent", "")).strip(),
                        "latest_handshake_human": str(user_data.get("latestHandshake", "")).strip(),
                    }
                )
            if normalized_records:
                return normalized_records

        records: list[dict[str, str]] = []

        def visit(item: object) -> None:
            if isinstance(item, list):
                for child in item:
                    visit(child)
                return
            if isinstance(item, dict):
                normalized: dict[str, str] = {}
                for key, value in item.items():
                    if isinstance(value, (str, int, float, bool)):
                        normalized[str(key).lower()] = str(value)
                if normalized:
                    records.append(normalized)
                for value in item.values():
                    if isinstance(value, (list, dict)):
                        visit(value)

        if payload is not None:
            visit(payload)
            return records

        for line in raw_table.splitlines():
            line = line.strip()
            if not line:
                continue
            normalized: dict[str, str] = {}
            for key, value in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)[:=]([^,;]+)", line):
                normalized[key.lower()] = value.strip().strip('"')
            if normalized:
                records.append(normalized)
        return records

    def _merge_clients_table(self, peers: list[dict[str, str]], raw_table: str) -> list[dict[str, str]]:
        records = self._normalize_clients_table_records(raw_table)
        if not records:
            return peers

        by_pubkey: dict[str, dict[str, str]] = {}
        by_ip: dict[str, dict[str, str]] = {}
        for record in records:
            public_key = (
                record.get("public_key")
                or record.get("publickey")
                or record.get("clientpublickey")
                or record.get("peer_public_key")
                or ""
            ).strip()
            assigned_ip = (
                record.get("assigned_ip")
                or record.get("address")
                or record.get("allowed_ips")
                or record.get("allowedips")
                or record.get("client_ip")
                or record.get("ip")
                or ""
            ).strip()
            name = (
                record.get("name")
                or record.get("client_name")
                or record.get("clientname")
                or record.get("remark")
                or record.get("description")
                or ""
            ).strip()
            row = {"name": name, "assigned_ip": assigned_ip}
            if public_key:
                by_pubkey[public_key] = row
            if assigned_ip:
                by_ip[assigned_ip.split(",")[0].strip()] = row

        merged: list[dict[str, str]] = []
        for peer in peers:
            candidate = dict(peer)
            public_key = candidate.get("public_key", "").strip()
            assigned_ip = candidate.get("allowed_ips", "").split(",")[0].strip()
            row = by_pubkey.get(public_key) or by_ip.get(assigned_ip)
            if row:
                if row.get("name"):
                    candidate["name"] = row["name"]
                if row.get("assigned_ip") and not candidate.get("allowed_ips"):
                    candidate["allowed_ips"] = row["assigned_ip"]
            merged.append(candidate)
        return merged

    def _merge_config_and_runtime_peers(
        self,
        config_peers: list[dict[str, str]],
        runtime_peers: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        runtime_by_public_key = {
            peer.get("public_key", "").strip(): peer
            for peer in runtime_peers
            if peer.get("public_key", "").strip()
        }
        merged: list[dict[str, str]] = []
        seen_public_keys: set[str] = set()

        for config_peer in config_peers:
            public_key = config_peer.get("public_key", "").strip()
            if not public_key:
                continue
            runtime_peer = runtime_by_public_key.get(public_key, {})
            merged_peer = dict(config_peer)
            for field in ("endpoint", "latest_handshake", "transfer_rx", "transfer_tx", "persistent_keepalive"):
                value = runtime_peer.get(field, "")
                if value:
                    merged_peer[field] = value
            merged.append(merged_peer)
            seen_public_keys.add(public_key)

        for runtime_peer in runtime_peers:
            public_key = runtime_peer.get("public_key", "").strip()
            if not public_key or public_key in seen_public_keys:
                continue
            merged.append(dict(runtime_peer))

        return merged

    async def fetch_peers(self, server: Server) -> list[dict[str, str]]:
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
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to import peers")
        runtime_peers = self._parse_peer_dump(result.stdout.strip())
        config_text = await self._fetch_config_text(server)
        config_peers = self._parse_peers_from_config(config_text)
        peers = self._merge_config_and_runtime_peers(config_peers, runtime_peers) if config_peers else runtime_peers
        clients_table = await self._fetch_clients_table(server)
        return self._merge_clients_table(peers, clients_table)

    def _make_name(self, db: Session, server: Server, public_key: str) -> str:
        suffix = public_key[-8:] if len(public_key) >= 8 else public_key
        base = f"{server.name}-peer-{suffix}"
        return self._make_unique_name(db, base)

    def _make_unique_name(self, db: Session, base: str) -> str:
        candidate = base
        index = 1
        while db.query(Client).filter(Client.name == candidate).first():
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    def import_into_db(self, db: Session, server: Server, peers: list[dict[str, str]]) -> ImportSummary:
        imported_count = 0
        updated_count = 0
        skipped_count = 0
        client_ids: list[int] = []
        seen_public_keys: set[str] = set()

        for peer in peers:
            public_key = peer.get("public_key")
            allowed_ips = peer.get("allowed_ips", "")
            if not public_key:
                skipped_count += 1
                continue
            seen_public_keys.add(public_key)

            assigned_ip = allowed_ips.split(",")[0].strip() if allowed_ips else ""
            if not assigned_ip:
                skipped_count += 1
                continue

            existing = (
                db.query(Client)
                .filter(Client.public_key == public_key, Client.server_id == server.id, Client.archived.is_(False))
                .first()
            )
            archived_match = (
                db.query(Client)
                .filter(Client.public_key == public_key, Client.archived.is_(True))
                .order_by(Client.updated_at.desc(), Client.id.desc())
                .first()
            )
            preferred_name = peer.get("name") or ""
            note = (
                f"Imported from {server.name}; endpoint={peer.get('endpoint', '')}; "
                f"rx={peer.get('transfer_rx', '')}; tx={peer.get('transfer_tx', '')}"
            )
            if existing:
                if preferred_name and existing.name.startswith(f"{server.name}-peer-"):
                    existing.name = self._make_unique_name(db, preferred_name)
                existing.assigned_ip = assigned_ip
                existing.import_note = note
                existing.source = ClientSource.IMPORTED
                existing.status = existing.status or "active"
                db.add(existing)
                db.commit()
                db.refresh(existing)
                updated_count += 1
                client_ids.append(existing.id)
                continue

            if archived_match:
                if preferred_name and archived_match.name.startswith(f"{server.name}-peer-"):
                    archived_match.name = self._make_unique_name(db, preferred_name)
                archived_match.assigned_ip = assigned_ip
                archived_match.import_note = note
                archived_match.server_id = server.id
                archived_match.archived = False
                archived_match.status = "active"
                archived_match.manual_disabled = False
                archived_match.policy_disabled_reason = None
                archived_match.runtime_connected = False
                db.add(archived_match)
                db.commit()
                db.refresh(archived_match)
                updated_count += 1
                client_ids.append(archived_match.id)
                continue

            client = Client(
                name=self._make_unique_name(db, preferred_name) if preferred_name else self._make_name(db, server, public_key),
                public_key=public_key,
                assigned_ip=assigned_ip,
                status="active",
                archived=False,
                manual_disabled=False,
                source=ClientSource.IMPORTED,
                server_id=server.id,
                import_note=note,
            )
            db.add(client)
            db.commit()
            db.refresh(client)
            imported_count += 1
            client_ids.append(client.id)

        stale_imports = (
            db.query(Client)
            .filter(Client.server_id == server.id, Client.source == ClientSource.IMPORTED, Client.archived.is_(False))
            .all()
        )
        for client in stale_imports:
            if client.public_key not in seen_public_keys:
                client.archived = True
                client.server_id = None
                client.status = "disabled"
                client.manual_disabled = False
                client.policy_disabled_reason = None
                client.runtime_connected = False
                db.add(client)
        db.commit()

        return ImportSummary(
            imported_count=imported_count,
            updated_count=updated_count,
            skipped_count=skipped_count,
            client_ids=client_ids,
        )
    def _parse_peer_dump(self, dump: str) -> list[dict[str, str]]:
        peers: list[dict[str, str]] = []
        for raw_line in dump.splitlines():
            parts = raw_line.strip().split("\t")
            if len(parts) < 9:
                continue
            interface_name = parts[0].strip()
            public_key = parts[1].strip()
            preshared_key = parts[2].strip()
            endpoint = parts[3].strip()
            allowed_ips = parts[4].strip()
            latest_handshake = parts[5].strip()
            transfer_rx = parts[6].strip()
            transfer_tx = parts[7].strip()
            persistent_keepalive = parts[8].strip()

            if (
                not public_key
                or public_key == "public_key"
                or interface_name == "interface"
                or allowed_ips in {"allowed ips", "allowed_ips", ""}
                or "/" not in allowed_ips
            ):
                continue

            peers.append(
                {
                    "public_key": public_key,
                    "preshared_key": preshared_key,
                    "allowed_ips": allowed_ips,
                    "endpoint": endpoint,
                    "latest_handshake": latest_handshake,
                    "transfer_rx": transfer_rx,
                    "transfer_tx": transfer_tx,
                    "persistent_keepalive": persistent_keepalive,
                }
            )
        return peers

    def _parse_peers_from_config(self, config_text: str) -> list[dict[str, str]]:
        peers: list[dict[str, str]] = []
        for block in re.split(r"\n\s*\n", config_text):
            if "[Peer]" not in block:
                continue
            name = ""
            comment_match = re.search(r"^#\s*client:\s*(.+)$", block, re.MULTILINE)
            if comment_match:
                name = comment_match.group(1).strip()
            public_key_match = re.search(r"^PublicKey\s*=\s*(.+)$", block, re.MULTILINE)
            allowed_ips_match = re.search(r"^AllowedIPs\s*=\s*(.+)$", block, re.MULTILINE)
            preshared_key_match = re.search(r"^PresharedKey\s*=\s*(.+)$", block, re.MULTILINE)
            endpoint_match = re.search(r"^Endpoint\s*=\s*(.+)$", block, re.MULTILINE)
            persistent_keepalive_match = re.search(r"^PersistentKeepalive\s*=\s*(.+)$", block, re.MULTILINE)
            if not public_key_match:
                continue
            allowed_ips = allowed_ips_match.group(1).strip() if allowed_ips_match else ""
            if not allowed_ips or "/" not in allowed_ips:
                continue
            peers.append(
                {
                    "name": name,
                    "public_key": public_key_match.group(1).strip(),
                    "allowed_ips": allowed_ips,
                    "preshared_key": preshared_key_match.group(1).strip() if preshared_key_match else "",
                    "endpoint": endpoint_match.group(1).strip() if endpoint_match else "",
                    "persistent_keepalive": persistent_keepalive_match.group(1).strip() if persistent_keepalive_match else "",
                }
            )
        return peers
