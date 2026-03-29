from __future__ import annotations

import json
import re
from dataclasses import dataclass
from shlex import quote

from app.models.server import Server
from app.services.bootstrap_commands import wrap_with_optional_sudo
from app.services.server_credentials import ServerCredentialsService
from app.services.server_runtime_paths import (
    build_read_clients_table_command,
    build_show_dump_command,
    get_docker_container,
    parse_runtime_details,
)
from app.services.ssh import SSHService

INSPECT_STANDARD_CONFIG_COMMAND = r"""
set -e
AWG_BIN=$(command -v awg || true)
WG_BIN=$(command -v wg || true)
IP_BIN=$(command -v ip || true)
DOCKER_BIN=$(command -v docker || true)
INTERFACE=""
LISTEN_PORT=""
ADDRESS_CIDR=""
PEER_COUNT="0"
CONFIG_PATH=""
DOCKER_CONTAINER=""
DOCKER_IMAGE=""
DOCKER_MOUNTS=""
RUNTIME="unknown"

find_awg_container() {
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

    printf '%s|%s|%s\n' "$score" "$name" "$image"
  done | sort -t'|' -k1,1nr | head -n1 | cut -d'|' -f2-3
}

pick_primary_interface() {
  interfaces="$1"
  if [ -z "$interfaces" ]; then
    return 0
  fi
  for preferred in awg0 wg0; do
    if printf '%s\n' "$interfaces" | tr ' ' '\n' | grep -Fx "$preferred" >/dev/null 2>&1; then
      printf '%s' "$preferred"
      return 0
    fi
  done
  printf '%s\n' "$interfaces" | tr ' ' '\n' | grep -E '^(awg|wg)[0-9]+$' | sort -V | head -n1
}

pick_primary_config_path() {
  for base in /etc/amnezia/amneziawg /etc/amneziawg /etc/wireguard; do
    for preferred in awg0 wg0; do
      if [ -f "$base/$preferred.conf" ]; then
        printf '%s' "$base/$preferred.conf"
        return 0
      fi
    done
  done
  return 1
}

if [ -n "$DOCKER_BIN" ]; then
  DOCKER_CONTAINER=$(find_awg_container)
fi

if [ -n "$AWG_BIN" ]; then
  INTERFACES=$($AWG_BIN show interfaces 2>/dev/null || true)
  INTERFACE=$(pick_primary_interface "$INTERFACES")
fi

if [ -n "$INTERFACE" ] && [ -n "$AWG_BIN" ]; then
  LISTEN_PORT=$($AWG_BIN show "$INTERFACE" listen-port 2>/dev/null || true)
  PEER_COUNT=$($AWG_BIN show "$INTERFACE" peers 2>/dev/null | wc -w | tr -d ' ' || true)
fi

CONFIG_PATH=$(pick_primary_config_path || true)
if [ -n "$CONFIG_PATH" ]; then
  if [ -z "$INTERFACE" ]; then
    INTERFACE=$(basename "$CONFIG_PATH" .conf)
  fi
fi

if [ -z "$CONFIG_PATH" ]; then
  for base in /etc/amnezia/amneziawg /etc/amneziawg /etc/wireguard; do
    if [ -n "$INTERFACE" ] && [ -f "$base/$INTERFACE.conf" ]; then
      CONFIG_PATH="$base/$INTERFACE.conf"
      break
    fi
  done
fi

if [ -n "$INTERFACE" ] && [ -n "$IP_BIN" ]; then
  ADDRESS_CIDR=$($IP_BIN -o -f inet addr show "$INTERFACE" 2>/dev/null | awk '{print $4}' | head -n1 || true)
fi

if [ -n "$DOCKER_BIN" ] && [ -n "$DOCKER_CONTAINER" ]; then
    DOCKER_IMAGE=${DOCKER_CONTAINER#*|}
    DOCKER_CONTAINER=${DOCKER_CONTAINER%%|*}
    DOCKER_MOUNTS=$(docker inspect "$DOCKER_CONTAINER" --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}' 2>/dev/null | tr '\n' ';' || true)
    RUNTIME="docker"

    if [ -z "$INTERFACE" ]; then
      INTERFACES=$(docker exec "$DOCKER_CONTAINER" sh -lc '
        if command -v awg >/dev/null 2>&1; then
          awg show interfaces 2>/dev/null
        elif command -v wg >/dev/null 2>&1; then
          wg show interfaces 2>/dev/null
        fi
      ' 2>/dev/null || true)
      INTERFACE=$(pick_primary_interface "$INTERFACES")
    fi

    if [ -z "$INTERFACE" ] || [ -z "$CONFIG_PATH" ]; then
      CONFIG_DISCOVERY=$(docker exec "$DOCKER_CONTAINER" sh -lc '
        for base in /etc/amnezia/amneziawg /etc/amneziawg /etc/wireguard /opt/amnezia/awg; do
          for preferred in awg0 wg0; do
            if [ -f "$base/$preferred.conf" ]; then
              printf "%s\n" "$base/$preferred.conf"
              exit 0
            fi
          done
        done
        find /etc/amnezia /etc/amneziawg /etc/wireguard /opt/amnezia -maxdepth 3 -type f -name "*.conf" 2>/dev/null | head -n1
      ' 2>/dev/null || true)
      if [ -n "$CONFIG_DISCOVERY" ]; then
        if [ -z "$CONFIG_PATH" ]; then
          CONFIG_PATH="$CONFIG_DISCOVERY"
        fi
        if [ -z "$INTERFACE" ] || [ "$(basename "$CONFIG_DISCOVERY" .conf)" = "awg0" ] || [ "$(basename "$CONFIG_DISCOVERY" .conf)" = "wg0" ]; then
          INTERFACE=$(basename "$CONFIG_DISCOVERY" .conf)
        fi
      fi
    fi

    if [ -n "$INTERFACE" ] && [ -z "$LISTEN_PORT" ]; then
      LISTEN_PORT=$(docker exec "$DOCKER_CONTAINER" sh -lc "
        if command -v awg >/dev/null 2>&1; then
          awg show '$INTERFACE' listen-port 2>/dev/null
        elif command -v wg >/dev/null 2>&1; then
          wg show '$INTERFACE' listen-port 2>/dev/null
        fi
      " 2>/dev/null || true)
    fi

    if [ -z "$ADDRESS_CIDR" ] && [ -n "$CONFIG_PATH" ]; then
      ADDRESS_CIDR=$(docker exec "$DOCKER_CONTAINER" sh -lc "
        awk -F'= ' '/^Address[[:space:]]*=/{print \$2; exit}' '$CONFIG_PATH' 2>/dev/null
      " 2>/dev/null || true)
    fi

    if [ -z "$LISTEN_PORT" ] && [ -n "$CONFIG_PATH" ]; then
      LISTEN_PORT=$(docker exec "$DOCKER_CONTAINER" sh -lc "
        awk -F'= ' '/^ListenPort[[:space:]]*=/{print \$2; exit}' '$CONFIG_PATH' 2>/dev/null
      " 2>/dev/null || true)
    fi

    if [ -n "$INTERFACE" ] && [ "$PEER_COUNT" = "0" ]; then
      PEER_COUNT=$(docker exec "$DOCKER_CONTAINER" sh -lc "
        if command -v awg >/dev/null 2>&1; then
          awg show '$INTERFACE' peers 2>/dev/null | wc -w | tr -d ' '
        elif command -v wg >/dev/null 2>&1; then
          wg show '$INTERFACE' peers 2>/dev/null | wc -w | tr -d ' '
        else
          printf '0'
        fi
      " 2>/dev/null || true)
    fi

    if [ "$PEER_COUNT" = "0" ] && [ -n "$CONFIG_PATH" ]; then
      PEER_COUNT=$(docker exec "$DOCKER_CONTAINER" sh -lc "
        awk '
        /^\\[Peer\\]/{count++}
        END{printf \"%d\", count+0}
        ' '$CONFIG_PATH' 2>/dev/null
      " 2>/dev/null || true)
    fi
fi

if [ "$RUNTIME" = "unknown" ] && [ -n "$INTERFACE" ]; then
  RUNTIME="custom"
fi

printf '{"runtime":"%s","interface":"%s","listen_port":"%s","address_cidr":"%s","peer_count":"%s","config_path":"%s","docker_container":"%s","docker_image":"%s","docker_mounts":"%s"}\n' \
  "$RUNTIME" "$INTERFACE" "$LISTEN_PORT" "$ADDRESS_CIDR" "$PEER_COUNT" "$CONFIG_PATH" "$DOCKER_CONTAINER" "$DOCKER_IMAGE" "$DOCKER_MOUNTS"
""".strip()


@dataclass
class StandardConfigInspection:
    runtime: str
    interface: str | None
    listen_port: int | None
    address_cidr: str | None
    peer_count: int
    config_path: str | None
    docker_container: str | None
    docker_mounts: str | None
    raw_json: str


class StandardConfigInspector:
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

    async def _fetch_config_text(
        self,
        server: Server,
        *,
        runtime: str,
        config_path: str | None,
        docker_container: str | None,
    ) -> str:
        if not config_path:
            return ""
        if runtime == "docker" and docker_container:
            command = f"docker exec {quote(docker_container)} sh -lc 'cat {quote(config_path)} 2>/dev/null || true'"
        else:
            command = wrap_with_optional_sudo(
                f"cat {quote(config_path)} 2>/dev/null || true",
                self.credentials.get_sudo_password(server),
            )
        return (await self._run(server, command)).strip()

    async def _fetch_peer_dump(
        self,
        server: Server,
        *,
        runtime: str,
        docker_container: str | None,
    ) -> str:
        runtime_details = parse_runtime_details(server)
        command = build_show_dump_command(server, runtime_details)
        if not get_docker_container(server, runtime_details):
            command = wrap_with_optional_sudo(command, self.credentials.get_sudo_password(server))
        return (await self._run(server, command)).strip()

    async def _fetch_clients_table(
        self,
        server: Server,
        *,
        runtime: str,
        docker_container: str | None,
    ) -> str:
        runtime_details = parse_runtime_details(server)
        command = build_read_clients_table_command(server, runtime_details)
        if not get_docker_container(server, runtime_details):
            command = wrap_with_optional_sudo(command, self.credentials.get_sudo_password(server))
        return (await self._run(server, command)).strip()

    def _parse_peer_dump(self, dump: str) -> list[dict[str, str]]:
        peers: list[dict[str, str]] = []
        for raw_line in dump.splitlines():
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
            public_key = parts[1].strip()
            if not public_key:
                continue
            peers.append(
                {
                    "public_key": public_key,
                    "allowed_ips": parts[4].strip(),
                    "endpoint": parts[3].strip(),
                    "latest_handshake": parts[5].strip(),
                    "transfer_rx": parts[6].strip(),
                    "transfer_tx": parts[7].strip(),
                    "persistent_keepalive": parts[8].strip(),
                }
            )
        return peers

    def _parse_peers_from_config(self, config_text: str) -> list[dict[str, str]]:
        peers: list[dict[str, str]] = []
        for block in re.split(r"\n\s*\n", config_text):
            if "[Peer]" not in block:
                continue
            public_key_match = re.search(r"^PublicKey\s*=\s*(.+)$", block, re.MULTILINE)
            allowed_ips_match = re.search(r"^AllowedIPs\s*=\s*(.+)$", block, re.MULTILINE)
            if not public_key_match:
                continue
            peers.append(
                {
                    "public_key": public_key_match.group(1).strip(),
                    "allowed_ips": allowed_ips_match.group(1).strip() if allowed_ips_match else "",
                }
            )
        return peers

    def _normalize_clients_table_records(self, raw_table: str) -> list[dict[str, str]]:
        if not raw_table:
            return []

        records: list[dict[str, str]] = []
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

        def visit(item: object) -> None:
            if isinstance(item, list):
                for child in item:
                    visit(child)
                return
            if isinstance(item, dict):
                normalized: dict[str, str] = {}
                for key, value in item.items():
                    lower_key = str(key).lower()
                    if isinstance(value, (str, int, float, bool)):
                        normalized[lower_key] = str(value)
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

    def _merge_clients_table(
        self,
        peers: list[dict[str, str]],
        clients_table: str,
    ) -> list[dict[str, str]]:
        records = self._normalize_clients_table_records(clients_table)
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
            if public_key:
                by_pubkey[public_key] = {"name": name, "assigned_ip": assigned_ip}
            if assigned_ip:
                by_ip[assigned_ip.split(",")[0].strip()] = {"name": name, "assigned_ip": assigned_ip}

        merged: list[dict[str, str]] = []
        for peer in peers:
            candidate = dict(peer)
            public_key = candidate.get("public_key", "").strip()
            assigned_ip = candidate.get("allowed_ips", "").split(",")[0].strip()
            table_match = by_pubkey.get(public_key) or by_ip.get(assigned_ip)
            if table_match:
                if table_match.get("name"):
                    candidate["name"] = table_match["name"]
                if table_match.get("assigned_ip") and not candidate.get("allowed_ips"):
                    candidate["allowed_ips"] = table_match["assigned_ip"]
            merged.append(candidate)
        return merged

    async def inspect(self, server: Server) -> StandardConfigInspection:
        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=self.credentials.get_ssh_password(server),
            private_key=self.credentials.get_private_key(server),
            command=INSPECT_STANDARD_CONFIG_COMMAND,
        )
        if result.exit_status != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to inspect existing standard config")

        payload = json.loads(result.stdout.strip().splitlines()[-1])
        listen_port_raw = payload.get("listen_port") or ""
        peer_count_raw = payload.get("peer_count") or "0"
        runtime = payload.get("runtime") or "unknown"
        config_path = payload.get("config_path") or None
        docker_container = payload.get("docker_container") or None

        config_text = await self._fetch_config_text(
            server,
            runtime=runtime,
            config_path=config_path,
            docker_container=docker_container,
        )
        peer_dump = await self._fetch_peer_dump(server, runtime=runtime, docker_container=docker_container)
        clients_table = await self._fetch_clients_table(server, runtime=runtime, docker_container=docker_container)
        peers = self._parse_peer_dump(peer_dump)
        if not peers and config_text:
            peers = self._parse_peers_from_config(config_text)
        peers = self._merge_clients_table(peers, clients_table)

        peer_count = int(peer_count_raw) if peer_count_raw.isdigit() else 0
        if peer_count == 0 and peers:
            peer_count = len(peers)

        payload["config_preview"] = config_text
        payload["peers"] = peers
        payload["clients_table_preview"] = clients_table
        payload["peer_count"] = str(peer_count)
        return StandardConfigInspection(
            runtime=runtime,
            interface=payload.get("interface") or None,
            listen_port=int(listen_port_raw) if listen_port_raw.isdigit() else None,
            address_cidr=payload.get("address_cidr") or None,
            peer_count=peer_count,
            config_path=config_path,
            docker_container=docker_container,
            docker_mounts=payload.get("docker_mounts") or None,
            raw_json=json.dumps(payload),
        )
