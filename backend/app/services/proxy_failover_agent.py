from __future__ import annotations

import json
import shlex
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.server import Server
from app.models.topology import Topology
from app.models.topology_node import TopologyNode
from app.services.bootstrap_commands import wrap_with_optional_sudo
from app.services.server_credentials import ServerCredentialsService
from app.services.ssh import SSHService

STATE_PATH = "/etc/awg-panel/proxy-failover-state.json"
STATUS_PATH = "/var/lib/awg-panel/proxy-failover-status.json"
SCRIPT_PATH = "/usr/local/bin/proxy-failover-agent.py"
UNIT_PATH = "/etc/systemd/system/proxy-failover-agent.service"
SERVICE_NAME = "proxy-failover-agent.service"

STATUS_READ_COMMAND = f"""sh -lc '
if [ -f {shlex.quote(STATUS_PATH)} ]; then
  cat {shlex.quote(STATUS_PATH)}
fi
'""".strip()


class ProxyFailoverAgentService:
    def __init__(self) -> None:
        self.ssh = SSHService()
        self.creds = ServerCredentialsService()

    def render_state(
        self,
        *,
        topology: Topology,
        proxy_server: Server,
        exit_nodes: list[TopologyNode],
        clients: list[Client],
        proxy_client_subnet: str,
        exit_interface_names: dict[int, str],
        exit_table_ids: dict[int, str],
    ) -> str:
        try:
            failover = json.loads(topology.failover_config_json) if topology.failover_config_json else {}
        except json.JSONDecodeError:
            failover = {}
        sorted_exit_nodes = sorted(exit_nodes, key=lambda item: item.priority)
        default_exit_server_id = sorted_exit_nodes[0].server_id if sorted_exit_nodes else None
        exits = []
        for node in sorted_exit_nodes:
            exits.append(
                {
                    "server_id": node.server_id,
                    "priority": node.priority,
                    "interface_name": exit_interface_names[node.server_id],
                    "table_id": int(exit_table_ids[node.server_id]),
                }
            )
        payload = {
            "topology_id": topology.id,
            "proxy_server_id": proxy_server.id,
            "proxy_client_subnet": proxy_client_subnet,
            "default_exit_server_id": default_exit_server_id,
            "active_exit_server_id": topology.active_exit_server_id or default_exit_server_id,
            "retries": int(failover.get("retries", 3) or 3),
            "interval_sec": int(failover.get("interval_sec", 10) or 10),
            "timeout_sec": int(failover.get("timeout_sec", 3) or 3),
            "failback_successes": int(failover.get("failback_successes", 2) or 2),
            "auto_failback": bool(failover.get("auto_failback", False)),
            "exits": exits,
            # Agent only switches the default subnet path; explicit per-client /32 overrides stay owned by topology deploy.
            "default_clients": [
                {
                    "client_id": client.id,
                    "assigned_ip": client.assigned_ip,
                }
                for client in clients
                if not client.archived
                and client.server_id == proxy_server.id
                and client.assigned_ip
                and not client.exit_server_id
            ],
            "override_clients": [
                {
                    "client_id": client.id,
                    "assigned_ip": client.assigned_ip,
                    "source_cidr": client.assigned_ip,
                    "preferred_exit_server_id": client.exit_server_id,
                }
                for client in clients
                if not client.archived
                and client.server_id == proxy_server.id
                and client.assigned_ip
                and client.exit_server_id
                and client.exit_server_id in exit_table_ids
            ],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    def render_script(self) -> str:
        return """#!/usr/bin/env python3
import json
import os
import subprocess
import time
from datetime import datetime, timezone

STATE_PATH = "/etc/awg-panel/proxy-failover-state.json"
STATUS_PATH = "/var/lib/awg-panel/proxy-failover-status.json"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def run(cmd, check=False):
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def save_status(payload):
    os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
    tmp_path = STATUS_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp_path, STATUS_PATH)


def get_latest_handshake(interface_name):
    if subprocess.run(["sh", "-lc", "command -v awg >/dev/null 2>&1"], check=False).returncode == 0:
        result = run(["awg", "show", interface_name, "latest-handshakes"])
    elif subprocess.run(["sh", "-lc", "command -v wg >/dev/null 2>&1"], check=False).returncode == 0:
        result = run(["wg", "show", interface_name, "latest-handshakes"])
    else:
        return 0
    if result.returncode != 0:
        return 0
    latest = 0
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        try:
            latest = max(latest, int(parts[1]))
        except ValueError:
            continue
    return latest


def is_exit_healthy(exit_item, interval_sec, timeout_sec):
    latest = get_latest_handshake(exit_item["interface_name"])
    if latest <= 0:
        return False
    grace = max(interval_sec + timeout_sec + 30, 45)
    return (time.time() - latest) <= grace


def remove_existing_rule(source):
    result = run(["ip", "rule", "show"])
    if result.returncode != 0:
        return
    for line in result.stdout.splitlines():
        if f"from {source} lookup " not in line:
            continue
        priority = line.split(":", 1)[0].strip()
        if not priority.isdigit():
            continue
        run(["ip", "rule", "del", "priority", priority])


def switch_default_exit(subnet, exit_item):
    remove_existing_rule(subnet)
    run(["ip", "rule", "add", "priority", "200", "from", subnet, "table", str(exit_item["table_id"])], check=True)


def switch_client_exit(source_cidr, exit_item, priority):
    remove_existing_rule(source_cidr)
    run(["ip", "rule", "add", "priority", str(priority), "from", source_cidr, "table", str(exit_item["table_id"])], check=True)


def find_exit(exits, server_id):
    for item in exits:
        if item["server_id"] == server_id:
            return item
    return None


def choose_best_exit(exits, health):
    return next((item for item in exits if health.get(item["server_id"])), None)


def main():
    runtime = load_json(STATUS_PATH, {
        "status": "starting",
        "active_exit_server_id": None,
        "failure_streak": 0,
        "primary_success_streak": 0,
        "override_clients": {},
    })
    while True:
        state = load_json(STATE_PATH, {})
        exits = sorted(state.get("exits", []), key=lambda item: item.get("priority", 10))
        subnet = state.get("proxy_client_subnet")
        override_clients = state.get("override_clients", [])
        default_exit_server_id = state.get("default_exit_server_id")
        active_exit_server_id = runtime.get("active_exit_server_id") or state.get("active_exit_server_id") or default_exit_server_id
        retries = int(state.get("retries", 3) or 3)
        interval_sec = int(state.get("interval_sec", 10) or 10)
        timeout_sec = int(state.get("timeout_sec", 3) or 3)
        failback_successes = int(state.get("failback_successes", 2) or 2)
        auto_failback = bool(state.get("auto_failback", False))
        status_payload = {
            "status": "running",
            "topology_id": state.get("topology_id"),
            "active_exit_server_id": active_exit_server_id,
            "last_check_at": utc_now(),
            "last_switch_at": runtime.get("last_switch_at"),
            "last_switch_reason": runtime.get("last_switch_reason"),
            "last_error": None,
            "failure_streak": int(runtime.get("failure_streak", 0) or 0),
            "primary_success_streak": int(runtime.get("primary_success_streak", 0) or 0),
            "service": "running",
            "override_clients": runtime.get("override_clients", {}),
            "moved_override_clients": 0,
        }
        try:
            if not subnet or not exits:
                raise RuntimeError("state is incomplete")
            health = {
                item["server_id"]: is_exit_healthy(item, interval_sec, timeout_sec)
                for item in exits
            }
            active_exit = find_exit(exits, active_exit_server_id) or find_exit(exits, default_exit_server_id) or exits[0]
            primary_exit = find_exit(exits, default_exit_server_id) or exits[0]

            if health.get(active_exit["server_id"]):
                status_payload["failure_streak"] = 0
            else:
                status_payload["failure_streak"] = int(status_payload["failure_streak"]) + 1

            if int(status_payload["failure_streak"]) >= retries:
                candidate = choose_best_exit(exits, health)
                if candidate and candidate["server_id"] != active_exit["server_id"]:
                    switch_default_exit(subnet, candidate)
                    active_exit = candidate
                    status_payload["active_exit_server_id"] = candidate["server_id"]
                    status_payload["last_switch_at"] = utc_now()
                    status_payload["last_switch_reason"] = "active-exit-healthcheck-failed"
                    status_payload["failure_streak"] = 0

            if auto_failback and primary_exit["server_id"] != status_payload["active_exit_server_id"]:
                if health.get(primary_exit["server_id"]):
                    status_payload["primary_success_streak"] = int(status_payload["primary_success_streak"]) + 1
                else:
                    status_payload["primary_success_streak"] = 0
                if int(status_payload["primary_success_streak"]) >= failback_successes:
                    switch_default_exit(subnet, primary_exit)
                    status_payload["active_exit_server_id"] = primary_exit["server_id"]
                    status_payload["last_switch_at"] = utc_now()
                    status_payload["last_switch_reason"] = "auto-failback-to-primary"
                    status_payload["primary_success_streak"] = 0
            else:
                status_payload["primary_success_streak"] = 0

            switch_default_exit(subnet, active_exit)

            runtime_overrides = runtime.get("override_clients", {})
            if not isinstance(runtime_overrides, dict):
                runtime_overrides = {}
            next_overrides = {}
            moved_override_clients = 0
            for index, item in enumerate(override_clients):
                source_cidr = item.get("source_cidr")
                preferred_exit_server_id = item.get("preferred_exit_server_id")
                client_id = str(item.get("client_id"))
                if not source_cidr or not preferred_exit_server_id:
                    continue
                preferred_exit = find_exit(exits, preferred_exit_server_id)
                if not preferred_exit:
                    continue

                client_runtime = runtime_overrides.get(client_id, {})
                if not isinstance(client_runtime, dict):
                    client_runtime = {}
                current_exit_server_id = int(client_runtime.get("active_exit_server_id") or preferred_exit_server_id)
                current_exit = find_exit(exits, current_exit_server_id) or preferred_exit
                failure_streak = int(client_runtime.get("failure_streak", 0) or 0)
                preferred_success_streak = int(client_runtime.get("preferred_success_streak", 0) or 0)

                if health.get(current_exit["server_id"]):
                    failure_streak = 0
                else:
                    failure_streak += 1

                if failure_streak >= retries:
                    candidate = choose_best_exit(exits, health)
                    if candidate:
                        current_exit = candidate
                        current_exit_server_id = candidate["server_id"]
                        failure_streak = 0

                if auto_failback and current_exit_server_id != preferred_exit_server_id:
                    if health.get(preferred_exit_server_id):
                        preferred_success_streak += 1
                    else:
                        preferred_success_streak = 0
                    if preferred_success_streak >= failback_successes:
                        current_exit = preferred_exit
                        current_exit_server_id = preferred_exit_server_id
                        preferred_success_streak = 0
                else:
                    preferred_success_streak = 0

                switch_client_exit(source_cidr, current_exit, 1000 + index)
                if current_exit_server_id != preferred_exit_server_id:
                    moved_override_clients += 1
                next_overrides[client_id] = {
                    "source_cidr": source_cidr,
                    "preferred_exit_server_id": preferred_exit_server_id,
                    "active_exit_server_id": current_exit_server_id,
                    "failure_streak": failure_streak,
                    "preferred_success_streak": preferred_success_streak,
                }

            status_payload["override_clients"] = next_overrides
            status_payload["moved_override_clients"] = moved_override_clients

        except Exception as exc:
            status_payload["status"] = "error"
            status_payload["service"] = "error"
            status_payload["last_error"] = str(exc)
        save_status(status_payload)
        runtime = status_payload
        time.sleep(max(interval_sec, 3))


if __name__ == "__main__":
    main()
""".strip() + "\n"

    def render_unit(self) -> str:
        return f"""[Unit]
Description=AWG proxy failover agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/env python3 {SCRIPT_PATH}
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
""".strip() + "\n"

    async def install(self, proxy_server: Server, state_content: str) -> None:
        password = self.creds.get_ssh_password(proxy_server)
        private_key = self.creds.get_private_key(proxy_server)
        sudo_password = self.creds.get_sudo_password(proxy_server)
        await self.ssh.upload_text_file(
            host=proxy_server.host,
            username=proxy_server.ssh_user,
            port=proxy_server.ssh_port,
            password=password,
            private_key=private_key,
            remote_path="/tmp/proxy-failover-state.json",
            content=state_content,
        )
        await self.ssh.upload_text_file(
            host=proxy_server.host,
            username=proxy_server.ssh_user,
            port=proxy_server.ssh_port,
            password=password,
            private_key=private_key,
            remote_path="/tmp/proxy-failover-agent.py",
            content=self.render_script(),
        )
        await self.ssh.upload_text_file(
            host=proxy_server.host,
            username=proxy_server.ssh_user,
            port=proxy_server.ssh_port,
            password=password,
            private_key=private_key,
            remote_path="/tmp/proxy-failover-agent.service",
            content=self.render_unit(),
        )
        command = wrap_with_optional_sudo(
            " && ".join(
                [
                    "mkdir -p /etc/awg-panel /var/lib/awg-panel",
                    f"mv /tmp/proxy-failover-state.json {shlex.quote(STATE_PATH)}",
                    f"mv /tmp/proxy-failover-agent.py {shlex.quote(SCRIPT_PATH)}",
                    f"mv /tmp/proxy-failover-agent.service {shlex.quote(UNIT_PATH)}",
                    f"chmod 600 {shlex.quote(STATE_PATH)}",
                    f"chmod 755 {shlex.quote(SCRIPT_PATH)}",
                    "systemctl daemon-reload",
                    f"systemctl enable --now {shlex.quote(SERVICE_NAME)}",
                ]
            ),
            sudo_password,
        )
        result = await self.ssh.run_command(
            host=proxy_server.host,
            username=proxy_server.ssh_user,
            port=proxy_server.ssh_port,
            password=password,
            private_key=private_key,
            command=command,
            timeout_seconds=120,
        )
        if result.exit_status != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to install proxy failover agent")

    async def fetch_status(self, server: Server) -> dict[str, object] | None:
        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=self.creds.get_ssh_password(server),
            private_key=self.creds.get_private_key(server),
            command=STATUS_READ_COMMAND,
            timeout_seconds=20,
        )
        if result.exit_status != 0 or not result.stdout.strip():
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def sync_status_to_db(self, db: Session, server: Server, status_payload: dict[str, object] | None) -> bool:
        try:
            metadata = json.loads(server.metadata_json) if server.metadata_json else {}
        except json.JSONDecodeError:
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}

        changed = False
        if status_payload:
            metadata["failover_agent"] = status_payload
        elif "failover_agent" in metadata:
            metadata.pop("failover_agent", None)
            changed = True

        next_metadata = json.dumps(metadata, ensure_ascii=False) if metadata else None
        if next_metadata != server.metadata_json:
            server.metadata_json = next_metadata
            changed = True

        topology_id = status_payload.get("topology_id") if status_payload else None
        active_exit_server_id = status_payload.get("active_exit_server_id") if status_payload else None
        if topology_id and active_exit_server_id:
            topology = db.query(Topology).filter(Topology.id == int(topology_id)).first()
            if topology and topology.active_exit_server_id != int(active_exit_server_id):
                topology.active_exit_server_id = int(active_exit_server_id)
                db.add(topology)
                changed = True

        if changed:
            db.add(server)
        return changed
