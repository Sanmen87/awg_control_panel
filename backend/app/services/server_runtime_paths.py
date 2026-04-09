from __future__ import annotations

import json
import os
import re
import shlex

from app.models.server import Server


DEFAULT_CLIENTS_TABLE_CANDIDATES = [
    "/opt/amnezia/awg/clientsTable",
    "/opt/amnezia/amneziawg/clientsTable",
    "/etc/amnezia/amneziawg/clientsTable",
    "/etc/amneziawg/clientsTable",
    "/etc/wireguard/clientsTable",
]

PANEL_INFRA_CONTAINER_PATTERN = re.compile(
    r"awg_control_panel[-_](backend|frontend|worker|scheduler|nginx|redis|db|postgres)([-_]|$)",
    re.IGNORECASE,
)


def parse_runtime_details(server: Server) -> dict[str, object]:
    if not server.live_runtime_details_json:
        return {}
    try:
        payload = json.loads(server.live_runtime_details_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def is_panel_infra_container(name: str | None) -> bool:
    if not isinstance(name, str):
        return False
    candidate = name.strip()
    if not candidate:
        return False
    return bool(PANEL_INFRA_CONTAINER_PATTERN.search(candidate))


def get_docker_container(server: Server, runtime_details: dict[str, object] | None = None) -> str | None:
    details = runtime_details or parse_runtime_details(server)
    docker_container = details.get("docker_container")
    if server.install_method.value == "docker" and isinstance(docker_container, str) and docker_container.strip():
        normalized = docker_container.strip()
        if not is_panel_infra_container(normalized):
            return normalized
    return None


def get_config_path(server: Server, runtime_details: dict[str, object] | None = None) -> str | None:
    details = runtime_details or parse_runtime_details(server)
    config_path = details.get("config_path")
    if isinstance(config_path, str) and config_path.strip():
        return config_path.strip()
    live_config_path = server.live_config_path
    if isinstance(live_config_path, str) and live_config_path.strip() and not live_config_path.startswith("docker://"):
        return live_config_path.strip()
    return None


def get_clients_table_candidates(server: Server, runtime_details: dict[str, object] | None = None) -> list[str]:
    details = runtime_details or parse_runtime_details(server)
    candidates: list[str] = []

    config_path = get_config_path(server, details)
    if config_path:
        config_dir = os.path.dirname(config_path.rstrip("/"))
        if config_dir:
            candidates.append(f"{config_dir}/clientsTable")

    preview_path = details.get("clients_table_path")
    if isinstance(preview_path, str) and preview_path.strip():
        candidates.append(preview_path.strip())

    candidates.extend(DEFAULT_CLIENTS_TABLE_CANDIDATES)

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def build_read_clients_table_command(server: Server, runtime_details: dict[str, object] | None = None) -> str:
    details = runtime_details or parse_runtime_details(server)
    docker_container = get_docker_container(server, details)
    read_script = " || ".join(f"cat {shlex.quote(path)} 2>/dev/null" for path in get_clients_table_candidates(server, details))
    if docker_container:
        return f"docker exec {shlex.quote(docker_container)} sh -lc {shlex.quote(read_script + ' || true')}"
    return f"sh -lc {shlex.quote(read_script + ' || true')}"


def build_show_dump_command(server: Server, runtime_details: dict[str, object] | None = None) -> str:
    details = runtime_details or parse_runtime_details(server)
    docker_container = get_docker_container(server, details)
    dump_script = "if command -v awg >/dev/null 2>&1; then awg show all dump; elif command -v wg >/dev/null 2>&1; then wg show all dump; fi"
    if docker_container:
        return f"docker exec {shlex.quote(docker_container)} sh -lc {shlex.quote(dump_script)}"
    return f"sh -lc {shlex.quote(dump_script)}"


def get_primary_clients_table_path(server: Server, runtime_details: dict[str, object] | None = None) -> str:
    return get_clients_table_candidates(server, runtime_details)[0]
