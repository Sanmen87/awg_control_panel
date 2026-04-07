from __future__ import annotations

import asyncio
import json
import shlex
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.agent_node import AgentNode
from app.models.server import Server
from app.services.bootstrap_commands import wrap_with_optional_sudo
from app.services.server_credentials import ServerCredentialsService
from app.services.ssh import SSHService

CONFIG_PATH = "/etc/awg-panel/agent-config.json"
SCRIPT_PATH = "/usr/local/bin/awg-panel-agent.py"
UNIT_PATH = "/etc/systemd/system/awg-panel-agent.service"
SERVICE_NAME = "awg-panel-agent.service"
STATE_DIR = "/var/lib/awg-panel"
STATUS_PATH = f"{STATE_DIR}/agent-status.json"
TASKS_DIR = f"{STATE_DIR}/agent-tasks"
RESULTS_DIR = f"{STATE_DIR}/agent-results"
POLICY_SNAPSHOT_PATH = f"{STATE_DIR}/client-policies.json"
POLICY_STATE_PATH = f"{STATE_DIR}/client-policy-state.json"


class ServerAgentService:
    def __init__(self) -> None:
        self.ssh = SSHService()
        self.creds = ServerCredentialsService()

    def ensure_enrolled(self, db: Session, server: Server) -> AgentNode:
        agent = db.query(AgentNode).filter(AgentNode.server_id == server.id).first()
        if agent is None:
            from secrets import token_urlsafe

            agent = AgentNode(
                server_id=server.id,
                token=token_urlsafe(32),
                status="enrolled",
            )
            db.add(agent)
            db.commit()
            db.refresh(agent)
        return agent

    def render_config(self, agent: AgentNode, server: Server) -> str:
        panel_base_url = settings.panel_public_base_url.strip().rstrip("/")
        payload = {
            "agent_id": agent.id,
            "server_id": server.id,
            "panel_base_url": panel_base_url,
            "sync_enabled": bool(panel_base_url),
            "api_prefix": settings.api_v1_prefix,
            "token": agent.token,
            "heartbeat_interval_sec": 30,
            "task_poll_interval_sec": 15,
            "state_dir": STATE_DIR,
            "version": "0.1.0",
        }
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    def render_script(self) -> str:
        return """#!/usr/bin/env python3
import json
import os
import glob
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CONFIG_PATH = "/etc/awg-panel/agent-config.json"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def request_json(method, url, token, payload=None, timeout=20):
    data = None
    headers = {
        "X-Agent-Token": token,
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else None


def command_stdout(command):
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=15)
    except Exception:
        return ""
    if result.returncode != 0:
        return result.stderr.strip() or result.stdout.strip()
    return result.stdout.strip()


def collect_runtime_snapshot():
    cpu_metrics = command_stdout(
        [
            "sh",
            "-lc",
            (
                '''cpu_line_1="$(grep "^cpu " /proc/stat)"
sleep 1
cpu_line_2="$(grep "^cpu " /proc/stat)"
awk -v a="$cpu_line_1" -v b="$cpu_line_2" '
BEGIN {
  split(a, x, " ");
  split(b, y, " ");
  idle1 = x[5] + x[6];
  idle2 = y[5] + y[6];
  total1 = 0;
  total2 = 0;
  for (i = 2; i <= 11; i++) {
    total1 += x[i];
    total2 += y[i];
  }
  diff_total = total2 - total1;
  diff_idle = idle2 - idle1;
  if (diff_total <= 0) {
    printf "0.00";
  } else {
    printf "%.2f", ((diff_total - diff_idle) / diff_total) * 100;
  }
}
'''
                + "'"
            ),
        ]
    )
    mem_total_kb = command_stdout(["sh", "-lc", "awk '/MemTotal:/ {print $2}' /proc/meminfo"])
    mem_available_kb = command_stdout(["sh", "-lc", "awk '/MemAvailable:/ {print $2}' /proc/meminfo"])
    try:
        mem_used_bytes = max((int(mem_total_kb or "0") - int(mem_available_kb or "0")), 0) * 1024
    except ValueError:
        mem_used_bytes = 0
    try:
        mem_total_bytes = int(mem_total_kb or "0") * 1024
    except ValueError:
        mem_total_bytes = 0
    disk_total_bytes = command_stdout(["sh", "-lc", "df -B1 / | awk 'NR==2 {print $2}'"])
    disk_used_bytes = command_stdout(["sh", "-lc", "df -B1 / | awk 'NR==2 {print $3}'"])
    iface = command_stdout(
        [
            "sh",
            "-lc",
            '''iface="$(awk '$2 == "00000000" {print $1; exit}' /proc/net/route)"
if [ -z "${iface:-}" ]; then
  iface="$(awk -F: 'NR>2 {gsub(/ /, "", $1); if ($1 != "lo") {print $1; exit}}' /proc/net/dev)"
fi
printf "%s" "${iface:-}" ''',
        ]
    )
    net_rx_bytes_total = "0"
    net_tx_bytes_total = "0"
    if iface:
        net_line = command_stdout(["sh", "-lc", f'grep -E "^[[:space:]]*{iface}:" /proc/net/dev | head -n1 || true'])
        if net_line:
            net_rx_bytes_total = command_stdout(["sh", "-lc", f'printf "%s\\n" {json.dumps(net_line)} | tr ":" " " | awk "{{print $2}}"'])
            net_tx_bytes_total = command_stdout(["sh", "-lc", f'printf "%s\\n" {json.dumps(net_line)} | tr ":" " " | awk "{{print $10}}"'])
    uptime_seconds = command_stdout(["sh", "-lc", "cut -d. -f1 /proc/uptime"])
    loadavg = command_stdout(["sh", "-lc", "cat /proc/loadavg"])
    load_parts = loadavg.split()
    container_status = command_stdout(
        ["sh", "-lc", 'if command -v docker >/dev/null 2>&1; then docker inspect -f "{{.State.Status}}" amnezia-awg 2>/dev/null || true; fi']
    )
    payload = {
        "collected_at": utc_now(),
        "hostname": socket.gethostname(),
        "cpu_percent": cpu_metrics or "0.00",
        "memory_total_bytes": str(mem_total_bytes),
        "memory_used_bytes": str(mem_used_bytes),
        "disk_total_bytes": disk_total_bytes or "0",
        "disk_used_bytes": disk_used_bytes or "0",
        "network_interface": iface,
        "network_rx_bytes_total": net_rx_bytes_total or "0",
        "network_tx_bytes_total": net_tx_bytes_total or "0",
        "uptime_seconds": uptime_seconds or "0",
        "load1": load_parts[0] if len(load_parts) > 0 else "0",
        "load5": load_parts[1] if len(load_parts) > 1 else "0",
        "load15": load_parts[2] if len(load_parts) > 2 else "0",
        "container_status": container_status or "",
        "awg_dump": command_stdout(["sh", "-lc", "if command -v awg >/dev/null 2>&1; then awg show all dump; elif command -v wg >/dev/null 2>&1; then wg show all dump; fi"]),
    }
    return payload


def collect_traffic_counters():
    payload = {
        "collected_at": utc_now(),
        "netdev": command_stdout(["sh", "-lc", "cat /proc/net/dev 2>/dev/null || true"]),
        "awg_dump": command_stdout(["sh", "-lc", "if command -v awg >/dev/null 2>&1; then awg show all dump; elif command -v wg >/dev/null 2>&1; then wg show all dump; fi"]),
    }
    return payload


def read_clients_table():
    content = command_stdout(
        [
            "sh",
            "-lc",
            "cat /opt/amnezia/awg/clientsTable 2>/dev/null || "
            "cat /opt/amnezia/amneziawg/clientsTable 2>/dev/null || "
            "cat /etc/amnezia/amneziawg/clientsTable 2>/dev/null || "
            "cat /etc/amneziawg/clientsTable 2>/dev/null || "
            "cat /etc/wireguard/clientsTable 2>/dev/null || true",
        ]
    )
    return {
        "collected_at": utc_now(),
        "content": content,
    }


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def parse_show_dump(output):
    stats_by_public_key = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 8:
            parts = line.split()
        if len(parts) == 5 or len(parts) < 9:
            continue
        public_key = parts[1].strip()
        if not public_key:
            continue
        stats_by_public_key[public_key] = {
            "allowed_ips": parts[4].strip(),
            "latest_handshake_at": int(parts[5].strip() or "0"),
            "rx_total": int(parts[6].strip() or "0"),
            "tx_total": int(parts[7].strip() or "0"),
        }
    return stats_by_public_key


def format_bytes_human(value):
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(max(int(value or 0), 0))
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.2f} {units[unit_index]}"


def format_handshake_human(latest_handshake_at):
    if int(latest_handshake_at or 0) <= 0:
        return ""
    delta = datetime.now(timezone.utc) - datetime.fromtimestamp(int(latest_handshake_at), timezone.utc)
    total_seconds = max(int(delta.total_seconds()), 0)
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return ", ".join(parts[:3]) + " ago"


def is_connected(latest_handshake_at):
    if int(latest_handshake_at or 0) <= 0:
        return False
    latest = datetime.fromtimestamp(int(latest_handshake_at), timezone.utc)
    return (datetime.now(timezone.utc) - latest) <= timedelta(minutes=3)


def is_within_quiet_hours(client_policy, now):
    start_minute = client_policy.get("quiet_hours_start_minute")
    end_minute = client_policy.get("quiet_hours_end_minute")
    if start_minute is None or end_minute is None:
        return False
    timezone_name = client_policy.get("quiet_hours_timezone") or "UTC"
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        tz = timezone.utc
    local_now = now.astimezone(tz)
    current_minute = local_now.hour * 60 + local_now.minute
    if start_minute == end_minute:
        return True
    if start_minute < end_minute:
        return start_minute <= current_minute < end_minute
    return current_minute >= start_minute or current_minute < end_minute


def resolve_policy_reason(client_policy, rolling_total, now):
    traffic_limit_mb = client_policy.get("traffic_limit_mb")
    if traffic_limit_mb:
        limit_bytes = int(traffic_limit_mb) * 1024 * 1024
        if rolling_total > limit_bytes:
            return "traffic_limit"
    expires_at = client_policy.get("expires_at")
    if expires_at:
        try:
            expires_dt = datetime.fromisoformat(expires_at)
            if expires_dt.tzinfo is None:
                expires_dt = expires_dt.replace(tzinfo=timezone.utc)
            if now >= expires_dt.astimezone(timezone.utc):
                return "expired"
        except ValueError:
            pass
    if is_within_quiet_hours(client_policy, now):
        return "quiet_hours"
    return None


def parse_config_blocks(config_text):
    interface_lines = []
    peers = []
    current_section = None
    current_peer_lines = []

    def flush_peer():
        nonlocal current_peer_lines
        if not current_peer_lines:
            return
        public_key = ""
        for line in current_peer_lines:
            stripped = line.strip()
            if stripped.startswith("PublicKey") and "=" in stripped:
                public_key = stripped.split("=", 1)[1].strip()
                break
        peers.append({
            "public_key": public_key,
            "raw_lines": list(current_peer_lines),
        })
        current_peer_lines = []

    for raw_line in config_text.splitlines():
        stripped = raw_line.strip()
        if stripped == "[Interface]":
            flush_peer()
            current_section = "interface"
            interface_lines = ["[Interface]"]
            continue
        if stripped == "[Peer]":
            flush_peer()
            current_section = "peer"
            current_peer_lines = ["[Peer]"]
            continue
        if current_section == "interface":
            interface_lines.append(raw_line)
        elif current_section == "peer":
            current_peer_lines.append(raw_line)
    flush_peer()
    return interface_lines, peers


def render_policy_config(config_text, policy_clients, disabled_public_keys, peer_backups):
    interface_lines, peers = parse_config_blocks(config_text)
    peer_by_public_key = {}
    ordered_policy_keys = []
    for client_policy in policy_clients:
        public_key = str(client_policy.get("public_key") or "").strip()
        if not public_key:
            continue
        peer_by_public_key[public_key] = client_policy
        ordered_policy_keys.append(public_key)

    for peer in peers:
        public_key = peer.get("public_key") or ""
        if public_key in peer_by_public_key:
            peer_backups[public_key] = "\n".join(peer.get("raw_lines") or []).strip()

    blocks = ["\n".join(interface_lines).strip() or "[Interface]"]
    included = set()
    for peer in peers:
        public_key = peer.get("public_key") or ""
        raw_block = "\n".join(peer.get("raw_lines") or []).strip()
        if not raw_block:
            continue
        if public_key in peer_by_public_key:
            if public_key in disabled_public_keys:
                continue
            blocks.append(raw_block)
            included.add(public_key)
        else:
            blocks.append(raw_block)

    for public_key in ordered_policy_keys:
        if public_key in included or public_key in disabled_public_keys:
            continue
        backup_block = peer_backups.get(public_key)
        if backup_block:
            blocks.append(backup_block)

    return "\n\n".join([block for block in blocks if block.strip()]).strip() + "\n"


def apply_live_config(runtime_payload, rendered_config):
    runtime = runtime_payload.get("runtime") or "unknown"
    config_path = runtime_payload.get("config_path") or ""
    interface_name = runtime_payload.get("interface_name") or "awg0"
    docker_container = runtime_payload.get("docker_container") or ""
    if not config_path:
        raise RuntimeError("Policy enforcement requires config_path")

    temp_path = "/tmp/awg-policy-enforced.conf"
    with open(temp_path, "w", encoding="utf-8") as fh:
        fh.write(rendered_config)

    if runtime == "docker" and docker_container:
        result = subprocess.run(
            ["docker", "cp", temp_path, f"{docker_container}:{config_path}"],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to copy policy config into container")
        inner_command = (
            f"chmod 600 {config_path} 2>/dev/null || true && "
            f"if command -v wg >/dev/null 2>&1 && command -v wg-quick >/dev/null 2>&1; then "
            f"(wg-quick down {config_path} || true) && wg-quick up {config_path}; "
            f"elif command -v awg >/dev/null 2>&1 && command -v awg-quick >/dev/null 2>&1; then "
            f"(awg-quick down {config_path} || true) && awg-quick up {config_path}; "
            f"else exit 44; fi"
        )
        result = subprocess.run(
            ["docker", "exec", docker_container, "sh", "-lc", inner_command],
            text=True,
            capture_output=True,
            check=False,
            timeout=90,
        )
    else:
        command = (
            f"set -e && "
            f"cp {json.dumps(config_path)} {json.dumps(config_path + '.bak.agent')} 2>/dev/null || true && "
            f"mv {json.dumps(temp_path)} {json.dumps(config_path)} && "
            f"chmod 600 {json.dumps(config_path)} && "
            f"(awg-quick down {json.dumps(interface_name)} || wg-quick down {json.dumps(interface_name)} || true) && "
            f"(awg-quick up {json.dumps(interface_name)} || wg-quick up {json.dumps(interface_name)})"
        )
        result = subprocess.run(["sh", "-lc", command], text=True, capture_output=True, check=False, timeout=90)
    try:
        os.remove(temp_path)
    except FileNotFoundError:
        pass
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to apply policy-enforced config")


def enforce_client_policies(payload):
    config = load_config()
    state_dir = config.get("state_dir") or "/var/lib/awg-panel"
    snapshot_path = os.path.join(state_dir, "client-policies.json")
    policy_state_path = os.path.join(state_dir, "client-policy-state.json")
    snapshot = load_json(snapshot_path, {})
    if not isinstance(snapshot, dict):
        raise RuntimeError("Client policy snapshot is missing or invalid")
    policy_clients = snapshot.get("clients")
    runtime_payload = snapshot.get("runtime")
    if not isinstance(policy_clients, list) or not isinstance(runtime_payload, dict):
        raise RuntimeError("Client policy snapshot is incomplete")

    awg_dump = command_stdout(["sh", "-lc", "if command -v awg >/dev/null 2>&1; then awg show all dump; elif command -v wg >/dev/null 2>&1; then wg show all dump; fi"])
    stats_by_public_key = parse_show_dump(awg_dump)
    config_path = str(runtime_payload.get("config_path") or "")
    docker_container = str(runtime_payload.get("docker_container") or "")
    if docker_container:
        current_config = command_stdout(["docker", "exec", docker_container, "sh", "-lc", f"cat {config_path} 2>/dev/null || true"])
    else:
        current_config = command_stdout(["sh", "-lc", f"cat {json.dumps(config_path)} 2>/dev/null || true"])
    policy_state = load_json(policy_state_path, {"version": 1, "clients": {}, "peer_backups": {}})
    if not isinstance(policy_state, dict):
        policy_state = {"version": 1, "clients": {}, "peer_backups": {}}
    state_clients = policy_state.setdefault("clients", {})
    peer_backups = policy_state.setdefault("peer_backups", {})

    now = datetime.now(timezone.utc)
    disabled_public_keys = set()
    policy_client_state = {}
    for client_policy in policy_clients:
        if not isinstance(client_policy, dict):
            continue
        public_key = str(client_policy.get("public_key") or "").strip()
        if not public_key:
            continue
        client_state = state_clients.get(public_key) or {"samples": []}
        stats = stats_by_public_key.get(public_key) or {}
        rx_total = int(stats.get("rx_total") or client_state.get("last_rx_total") or 0)
        tx_total = int(stats.get("tx_total") or client_state.get("last_tx_total") or 0)
        prev_rx_total = int(client_state.get("last_rx_total") or 0)
        prev_tx_total = int(client_state.get("last_tx_total") or 0)
        rx_delta = rx_total - prev_rx_total if rx_total >= prev_rx_total else rx_total
        tx_delta = tx_total - prev_tx_total if tx_total >= prev_tx_total else tx_total
        samples = [item for item in client_state.get("samples", []) if isinstance(item, dict)]
        samples = [item for item in samples if str(item.get("sampled_at") or "") >= (now - timedelta(days=30)).isoformat()]
        samples.append({
            "sampled_at": now.isoformat(),
            "rx_delta": rx_delta,
            "tx_delta": tx_delta,
        })
        rolling_rx = sum(int(item.get("rx_delta") or 0) for item in samples)
        rolling_tx = sum(int(item.get("tx_delta") or 0) for item in samples)
        policy_reason = resolve_policy_reason(client_policy, rolling_rx + rolling_tx, now)
        manual_disabled = bool(client_policy.get("manual_disabled"))
        effective_disabled = manual_disabled or bool(policy_reason)
        if effective_disabled:
            disabled_public_keys.add(public_key)
        latest_handshake_at = int(stats.get("latest_handshake_at") or 0)
        updated_state = {
            "name": client_policy.get("name"),
            "assigned_ip": client_policy.get("assigned_ip"),
            "manual_disabled": manual_disabled,
            "last_rx_total": rx_total,
            "last_tx_total": tx_total,
            "rolling_rx": rolling_rx,
            "rolling_tx": rolling_tx,
            "latest_handshake_at": latest_handshake_at,
            "latest_handshake_human": format_handshake_human(latest_handshake_at),
            "data_received_human": format_bytes_human(rx_total),
            "data_sent_human": format_bytes_human(tx_total),
            "runtime_connected": is_connected(latest_handshake_at),
            "policy_disabled_reason": policy_reason,
            "effective_disabled": effective_disabled,
            "samples": samples,
        }
        state_clients[public_key] = updated_state
        policy_client_state[public_key] = updated_state

    rendered_config = render_policy_config(current_config, policy_clients, disabled_public_keys, peer_backups)
    last_applied_config = str(policy_state.get("last_applied_config") or "")
    applied = False
    if current_config.strip() and rendered_config.strip() and rendered_config != current_config and rendered_config != last_applied_config:
        apply_live_config(runtime_payload, rendered_config)
        applied = True
    policy_state.update(
        {
            "version": 1,
            "collected_at": now.isoformat(),
            "runtime": runtime_payload,
            "clients": policy_client_state,
            "peer_backups": peer_backups,
            "last_applied_config": rendered_config,
            "policy_disabled_count": len(disabled_public_keys),
            "policy_client_count": len(policy_client_state),
            "applied_at": now.isoformat() if applied else policy_state.get("applied_at"),
        }
    )
    save_json(policy_state_path, policy_state)
    return {
        "collected_at": now.isoformat(),
        "clients": policy_client_state,
        "policy_disabled_count": len(disabled_public_keys),
        "policy_client_count": len(policy_client_state),
        "config_applied": applied,
    }


def inspect_standard_runtime():
    runtime = "unknown"
    docker_container = ""
    docker_image = ""
    docker_mounts = ""
    interface = command_stdout(
        [
            "sh",
            "-lc",
            '''if command -v awg >/dev/null 2>&1; then
  awg show interfaces 2>/dev/null
elif command -v wg >/dev/null 2>&1; then
  wg show interfaces 2>/dev/null
fi''',
        ]
    )
    interfaces = [item for item in interface.split() if item.strip()]
    if "awg0" in interfaces:
        primary_interface = "awg0"
    elif "wg0" in interfaces:
        primary_interface = "wg0"
    else:
        primary_interface = interfaces[0] if interfaces else ""

    config_path = command_stdout(
        [
            "sh",
            "-lc",
                '''for base in /etc/amnezia/amneziawg /etc/amneziawg /etc/wireguard /opt/amnezia/awg; do
  for preferred in awg0 wg0; do
    if [ -f "$base/$preferred.conf" ]; then
      printf "%s" "$base/$preferred.conf"
      exit 0
    fi
  done
done
find /etc/amnezia /etc/amneziawg /etc/wireguard /opt/amnezia -maxdepth 3 -type f -name "*.conf" 2>/dev/null | head -n1 | tr -d "\\n"''',
        ]
    )
    if config_path and not primary_interface:
        primary_interface = os.path.basename(config_path).rsplit(".", 1)[0]

    listen_port = ""
    address_cidr = ""
    config_preview = ""
    if config_path:
        config_preview = command_stdout(["sh", "-lc", f"cat {json.dumps(config_path)} 2>/dev/null || true"])
        listen_port = command_stdout(
            ["sh", "-lc", f"awk -F'= ' '/^ListenPort[[:space:]]*=/' {{print $2; exit}} {json.dumps(config_path)} 2>/dev/null || true"]
        )
        address_cidr = command_stdout(
            ["sh", "-lc", f"awk -F'= ' '/^Address[[:space:]]*=/' {{print $2; exit}} {json.dumps(config_path)} 2>/dev/null || true"]
        )

    awg_dump = command_stdout(
        ["sh", "-lc", "if command -v awg >/dev/null 2>&1; then awg show all dump; elif command -v wg >/dev/null 2>&1; then wg show all dump; fi"]
    )
    peer_count = "0"
    if primary_interface:
        peer_count = command_stdout(
            [
                "sh",
                "-lc",
                f'''if command -v awg >/dev/null 2>&1; then
  awg show {json.dumps(primary_interface)} peers 2>/dev/null | wc -w | tr -d ' '
elif command -v wg >/dev/null 2>&1; then
  wg show {json.dumps(primary_interface)} peers 2>/dev/null | wc -w | tr -d ' '
else
  printf '0'
fi''',
            ]
        )
    if not peer_count and config_preview:
        peer_count = str(config_preview.count("[Peer]"))

    clients_table_payload = read_clients_table()

    if command_stdout(["sh", "-lc", "command -v docker >/dev/null 2>&1 && printf yes || true"]) == "yes":
        docker_container = command_stdout(
            [
                "sh",
                "-lc",
                r'''docker ps --format '{{.Names}}|{{.Image}}' 2>/dev/null | awk -F'|' '
/awg|wireguard/ && $0 !~ /dns/ {print $1; exit}
''',
            ]
        )
        if docker_container:
            runtime = "docker"
            docker_image = command_stdout(
                ["sh", "-lc", f"docker inspect -f '{{{{.Config.Image}}}}' {json.dumps(docker_container)} 2>/dev/null || true"]
            )
            docker_mounts = command_stdout(
                [
                    "sh",
                    "-lc",
                    f"docker inspect {json.dumps(docker_container)} --format '{{{{range .Mounts}}}}{{{{println .Source \"->\" .Destination}}}}{{{{end}}}}' 2>/dev/null | tr '\\n' ';' || true",
                ]
            )
    if runtime == "unknown" and primary_interface:
        runtime = "custom"

    return {
        "collected_at": utc_now(),
        "runtime": runtime,
        "interface": primary_interface,
        "listen_port": listen_port,
        "address_cidr": address_cidr,
        "peer_count": peer_count or "0",
        "config_path": config_path,
        "docker_container": docker_container,
        "docker_image": docker_image,
        "docker_mounts": docker_mounts,
        "config_preview": config_preview,
        "clients_table_preview": str(clients_table_payload.get("content") or ""),
        "awg_dump": awg_dump,
    }


HANDLERS = {
    "noop": lambda payload: {"ok": True, "echo": payload},
    "collect-runtime-snapshot": lambda payload: collect_runtime_snapshot(),
    "collect-traffic-counters": lambda payload: collect_traffic_counters(),
    "read-clients-table": lambda payload: read_clients_table(),
    "enforce-client-policies": lambda payload: enforce_client_policies(payload),
    "inspect-standard-runtime": lambda payload: inspect_standard_runtime(),
}


def process_local_tasks(tasks_dir, results_dir):
    for task_path in sorted(glob.glob(os.path.join(tasks_dir, "*.json"))):
        requeue_task = None
        try:
            with open(task_path, "r", encoding="utf-8") as fh:
                task = json.load(fh)
            task_id = task.get("id") or os.path.basename(task_path).split(".", 1)[0]
            task_type = task.get("task_type")
            payload = task.get("payload")
            repeat_task = isinstance(payload, dict) and bool(payload.get("repeat"))
            silent_task = isinstance(payload, dict) and bool(payload.get("silent"))
            if task_type not in HANDLERS:
                result = {
                    "id": task_id,
                    "status": "failed",
                    "last_error": f"Unsupported task type: {task_type}",
                    "completed_at": utc_now(),
                }
            else:
                try:
                    output = HANDLERS[task_type](payload)
                    result = {
                        "id": task_id,
                        "status": "succeeded",
                        "result": output,
                        "completed_at": utc_now(),
                    }
                except Exception as exc:
                    result = {
                        "id": task_id,
                        "status": "failed",
                        "last_error": str(exc),
                        "completed_at": utc_now(),
                    }
            if not silent_task or result.get("status") == "failed":
                save_json(os.path.join(results_dir, f"{task_id}.json"), result)
            if repeat_task:
                requeue_task = task
        finally:
            if requeue_task is not None:
                save_json(task_path, requeue_task)
            else:
                try:
                    os.remove(task_path)
                except FileNotFoundError:
                    pass


def main():
    config = load_config()
    state_dir = config.get("state_dir") or "/var/lib/awg-panel"
    status_path = os.path.join(state_dir, "agent-status.json")
    tasks_dir = os.path.join(state_dir, "agent-tasks")
    results_dir = os.path.join(state_dir, "agent-results")
    os.makedirs(tasks_dir, exist_ok=True)
    os.makedirs(results_dir, exist_ok=True)
    sync_enabled = bool(config.get("sync_enabled")) and bool(config.get("panel_base_url"))
    base = (config.get("panel_base_url") or "") + config["api_prefix"] + "/agents/sync"
    token = config["token"]
    heartbeat_interval = int(config.get("heartbeat_interval_sec", 30))
    task_poll_interval = int(config.get("task_poll_interval_sec", 15))
    version = config.get("version") or "0.1.0"
    capabilities = {
        "handlers": sorted(HANDLERS.keys()),
        "local_task_queue": True,
    }
    next_heartbeat = 0
    next_poll = 0
    while True:
        now = time.monotonic()
        policy_state = load_json(os.path.join(state_dir, "client-policy-state.json"), {}) or {}
        local_state = {
            "collected_at": utc_now(),
            "hostname": socket.gethostname(),
            "sync_enabled": sync_enabled,
            "pending_local_tasks": len(glob.glob(os.path.join(tasks_dir, "*.json"))),
            "pending_local_results": len(glob.glob(os.path.join(results_dir, "*.json"))),
            "policy_client_count": int(policy_state.get("policy_client_count") or 0) if isinstance(policy_state, dict) else 0,
            "policy_disabled_count": int(policy_state.get("policy_disabled_count") or 0) if isinstance(policy_state, dict) else 0,
        }
        save_json(
            status_path,
            {
                "status": "running",
                "version": version,
                "capabilities": capabilities,
                "local_state": local_state,
                "updated_at": utc_now(),
            },
        )
        try:
            if now >= next_poll:
                process_local_tasks(tasks_dir, results_dir)
                next_poll = now + task_poll_interval

            if not sync_enabled:
                time.sleep(2)
                continue

            if now >= next_heartbeat:
                request_json(
                    "POST",
                    base + "/heartbeat",
                    token,
                    {
                        "version": version,
                        "capabilities_json": json.dumps(capabilities, ensure_ascii=False),
                        "local_state_json": json.dumps(local_state, ensure_ascii=False),
                    },
                )
                next_heartbeat = now + heartbeat_interval

            if now >= next_poll:
                tasks = request_json("GET", base + "/tasks", token) or []
                for task in tasks:
                    task_id = task["id"]
                    task_type = task["task_type"]
                    payload_raw = task.get("payload_json")
                    try:
                        task_payload = json.loads(payload_raw) if payload_raw else None
                    except Exception:
                        task_payload = payload_raw
                    if task_type not in HANDLERS:
                        request_json(
                            "POST",
                            base + f"/tasks/{task_id}/ack",
                            token,
                            {"status": "failed", "last_error": f"Unsupported task type: {task_type}"},
                        )
                        continue
                    try:
                        result = HANDLERS[task_type](task_payload)
                        request_json(
                            "POST",
                            base + f"/tasks/{task_id}/ack",
                            token,
                            {
                                "status": "succeeded",
                                "result_json": json.dumps(result, ensure_ascii=False),
                            },
                        )
                    except Exception as exc:
                        request_json(
                            "POST",
                            base + f"/tasks/{task_id}/ack",
                            token,
                            {"status": "failed", "last_error": str(exc)},
                        )
                next_poll = now + task_poll_interval
        except urllib.error.URLError:
            next_heartbeat = min(next_heartbeat, now + heartbeat_interval)
            next_poll = min(next_poll, now + task_poll_interval)
        except Exception:
            next_heartbeat = min(next_heartbeat, now + heartbeat_interval)
            next_poll = min(next_poll, now + task_poll_interval)
        time.sleep(2)


if __name__ == "__main__":
    main()
""".strip() + "\n"

    def render_unit(self) -> str:
        return f"""[Unit]
Description=AWG Control Panel server agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/env python3 {SCRIPT_PATH}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
""".strip() + "\n"

    async def install(self, server: Server, agent: AgentNode) -> None:
        password = self.creds.get_ssh_password(server)
        private_key = self.creds.get_private_key(server)
        sudo_password = self.creds.get_sudo_password(server)

        await self.ssh.upload_text_file(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            remote_path="/tmp/awg-panel-agent.py",
            content=self.render_script(),
        )
        await self.ssh.upload_text_file(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            remote_path="/tmp/awg-panel-agent.service",
            content=self.render_unit(),
        )
        await self.ssh.upload_text_file(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            remote_path="/tmp/awg-panel-agent-config.json",
            content=self.render_config(agent, server),
        )
        install_commands = [
            "set -e",
            "if command -v apt-get >/dev/null 2>&1; then export DEBIAN_FRONTEND=noninteractive; apt-get update; apt-get install -y python3; fi",
            "mkdir -p /etc/awg-panel /var/lib/awg-panel",
            f"mv /tmp/awg-panel-agent.py {shlex.quote(SCRIPT_PATH)}",
            f"mv /tmp/awg-panel-agent.service {shlex.quote(UNIT_PATH)}",
            f"mv /tmp/awg-panel-agent-config.json {shlex.quote(CONFIG_PATH)}",
            f"chmod 0755 {shlex.quote(SCRIPT_PATH)}",
            f"chmod 0644 {shlex.quote(UNIT_PATH)}",
            f"chmod 0600 {shlex.quote(CONFIG_PATH)}",
            "systemctl daemon-reload",
            f"systemctl enable --now {shlex.quote(SERVICE_NAME)}",
            f"systemctl restart {shlex.quote(SERVICE_NAME)}",
            f"systemctl is-active {shlex.quote(SERVICE_NAME)}",
        ]
        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            command=wrap_with_optional_sudo(" && ".join(install_commands), sudo_password),
            timeout_seconds=600,
        )
        if result.exit_status != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to install AWG panel agent")

    async def fetch_local_status(self, server: Server) -> dict[str, object] | None:
        password = self.creds.get_ssh_password(server)
        private_key = self.creds.get_private_key(server)
        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            command=f"sh -lc 'cat {shlex.quote(STATUS_PATH)} 2>/dev/null || true'",
            timeout_seconds=60,
        )
        if result.exit_status != 0 or not result.stdout.strip():
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

    async def sync_policy_snapshot(self, server: Server, snapshot_content: str) -> None:
        password = self.creds.get_ssh_password(server)
        private_key = self.creds.get_private_key(server)
        remote_tmp = "/tmp/awg-agent-client-policies.json"
        await self.ssh.upload_text_file(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            remote_path=remote_tmp,
            content=snapshot_content,
        )
        sudo_password = self.creds.get_sudo_password(server)
        command = wrap_with_optional_sudo(
            " && ".join(
                [
                    "set -e",
                    f"mkdir -p {shlex.quote(STATE_DIR)}",
                    f"mv {shlex.quote(remote_tmp)} {shlex.quote(POLICY_SNAPSHOT_PATH)}",
                    f"chmod 0600 {shlex.quote(POLICY_SNAPSHOT_PATH)}",
                ]
            ),
            sudo_password,
        )
        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            command=command,
            timeout_seconds=60,
        )
        if result.exit_status != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to sync client policy snapshot")

    async def fetch_policy_state(self, server: Server) -> dict[str, object] | None:
        password = self.creds.get_ssh_password(server)
        private_key = self.creds.get_private_key(server)
        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            command=f"sh -lc 'cat {shlex.quote(POLICY_STATE_PATH)} 2>/dev/null || true'",
            timeout_seconds=60,
        )
        if result.exit_status != 0 or not result.stdout.strip():
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    async def enqueue_local_task(self, server: Server, task_id: str, task_type: str, payload: dict[str, object] | None = None) -> None:
        password = self.creds.get_ssh_password(server)
        private_key = self.creds.get_private_key(server)
        task_content = json.dumps(
            {
                "id": task_id,
                "task_type": task_type,
                "payload": payload or {},
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n"
        remote_tmp = f"/tmp/awg-agent-task-{task_id}.json"
        await self.ssh.upload_text_file(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            remote_path=remote_tmp,
            content=task_content,
        )
        sudo_password = self.creds.get_sudo_password(server)
        command = wrap_with_optional_sudo(
            " && ".join(
                [
                    "set -e",
                    f"mkdir -p {shlex.quote(TASKS_DIR)}",
                    f"mv {shlex.quote(remote_tmp)} {shlex.quote(TASKS_DIR)}/{shlex.quote(task_id)}.json",
                ]
            ),
            sudo_password,
        )
        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            command=command,
            timeout_seconds=60,
        )
        if result.exit_status != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to enqueue local agent task")

    async def fetch_local_results(self, server: Server) -> list[dict[str, object]]:
        password = self.creds.get_ssh_password(server)
        private_key = self.creds.get_private_key(server)
        marker = "__AWG_PANEL_AGENT_RESULT__"
        command = (
            "sh -lc '"
            f"for file in {shlex.quote(RESULTS_DIR)}/*.json; do "
            '[ -f "$file" ] || continue; '
            'cat "$file"; '
            f'printf "\\n{marker}\\n"; '
            'rm -f "$file"; '
            "done'"
        )
        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            command=command,
            timeout_seconds=120,
        )
        if result.exit_status != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to fetch local agent results")
        chunks = [chunk.strip() for chunk in result.stdout.split(marker) if chunk.strip()]
        items: list[dict[str, object]] = []
        for chunk in chunks:
            try:
                payload = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                items.append(payload)
        return items

    async def fetch_local_result(self, server: Server, task_id: str) -> dict[str, object] | None:
        password = self.creds.get_ssh_password(server)
        private_key = self.creds.get_private_key(server)
        result_path = f"{RESULTS_DIR}/{task_id}.json"
        command = (
            "sh -lc '"
            f'if [ -f {shlex.quote(result_path)} ]; then '
            f'cat {shlex.quote(result_path)}; '
            f'rm -f {shlex.quote(result_path)}; '
            "fi'"
        )
        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            command=command,
            timeout_seconds=60,
        )
        if result.exit_status != 0 or not result.stdout.strip():
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    async def run_local_task(
        self,
        server: Server,
        task_type: str,
        payload: dict[str, object] | None = None,
        *,
        timeout_seconds: float = 30.0,
        poll_interval: float = 1.0,
    ) -> dict[str, object] | None:
        task_id = f"manual-{uuid.uuid4()}"
        await self.enqueue_local_task(server, task_id, task_type, payload)
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            result = await self.fetch_local_result(server, task_id)
            if result is not None:
                return result
            await asyncio.sleep(poll_interval)
        return None
