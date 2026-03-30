from __future__ import annotations

import ipaddress
import json
import re

from app.models.client import Client
from app.models.server import Server
from app.models.topology import TopologyType
from app.models.topology_node import TopologyNode, TopologyNodeRole
from app.services.topology_renderer import TopologyRenderer


class TopologyValidationResult:
    def __init__(self, *, topology_id: int, errors: list[str], warnings: list[str]) -> None:
        self.topology_id = topology_id
        self.errors = errors
        self.warnings = warnings

    @property
    def is_valid(self) -> bool:
        return not self.errors


class TopologyValidationService:
    def _proxy_exit_overlap_errors(
        self,
        topology_type: TopologyType,
        nodes: list[TopologyNode],
        servers_by_id: dict[int, Server] | None,
        topology_metadata_json: str | None,
    ) -> list[str]:
        if not servers_by_id:
            return []

        proxy_node = next((node for node in nodes if node.role == TopologyNodeRole.PROXY), None)
        exit_nodes = [node for node in nodes if node.role == TopologyNodeRole.EXIT]
        if not proxy_node or not exit_nodes:
            return []

        proxy_server = servers_by_id.get(proxy_node.server_id)
        if not proxy_server:
            return []

        topology_stub = type("TopologyStub", (), {"metadata_json": topology_metadata_json})()
        try:
            subnet = TopologyRenderer()._proxy_client_subnet(topology_stub)
            proxy_network = ipaddress.ip_network(subnet, strict=False)
        except ValueError:
            return [f"Invalid proxy client subnet configured for topology: {subnet}"]

        errors: list[str] = []
        for exit_node in exit_nodes:
            exit_server = servers_by_id.get(exit_node.server_id)
            if not exit_server:
                continue
            runtime_details_raw = getattr(exit_server, "live_runtime_details_json", None)
            if not runtime_details_raw:
                continue
            try:
                runtime_details = json.loads(runtime_details_raw)
            except json.JSONDecodeError:
                continue
            config_preview = runtime_details.get("config_preview") if isinstance(runtime_details, dict) else None
            if not isinstance(config_preview, str) or not config_preview.strip():
                continue

            for block in re.split(r"\n\s*\n", config_preview):
                if "[Peer]" not in block:
                    continue
                if "# service-exit-peer" in block:
                    continue
                # Any existing exit peer inside proxy client subnet will steal return traffic from proxy clients.
                match = re.search(r"^AllowedIPs\s*=\s*(.+)$", block, re.MULTILINE)
                if not match:
                    continue
                raw_allowed_ips = match.group(1).strip()
                for item in [part.strip() for part in raw_allowed_ips.split(",") if part.strip()]:
                    try:
                        network = ipaddress.ip_network(item, strict=False)
                    except ValueError:
                        continue
                    if network.version != proxy_network.version:
                        continue
                    if network.overlaps(proxy_network):
                        errors.append(
                            f"Exit server {exit_server.name} ({exit_server.host}) already has peer route {item} "
                            f"which overlaps proxy client subnet {proxy_network}."
                        )
                        break
        return errors

    def validate(
        self,
        topology_id: int,
        topology_type: TopologyType,
        nodes: list[TopologyNode],
        *,
        clients: list[Client] | None = None,
        servers_by_id: dict[int, Server] | None = None,
        topology_metadata_json: str | None = None,
        default_exit_server_id: int | None = None,
    ) -> TopologyValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        standard_nodes = [node for node in nodes if node.role == TopologyNodeRole.STANDARD_VPN]
        proxy_nodes = [node for node in nodes if node.role == TopologyNodeRole.PROXY]
        exit_nodes = [node for node in nodes if node.role == TopologyNodeRole.EXIT]
        secondary_proxy_nodes = [node for node in nodes if node.role == TopologyNodeRole.PROXY_SECONDARY]

        if topology_type == TopologyType.STANDARD:
            if len(standard_nodes) != 1:
                errors.append("Standard topology must contain exactly one standard-vpn node")
            if proxy_nodes or exit_nodes or secondary_proxy_nodes:
                errors.append("Standard topology cannot contain proxy, exit, or proxy-secondary nodes")

        if topology_type == TopologyType.PROXY_EXIT:
            if len(proxy_nodes) != 1:
                errors.append("Proxy-exit topology must contain exactly one proxy node")
            if len(exit_nodes) != 1:
                errors.append("Proxy-exit topology must contain exactly one exit node")
            if standard_nodes:
                errors.append("Proxy-exit topology cannot contain standard-vpn nodes")
            if not errors:
                errors.extend(self._proxy_exit_overlap_errors(topology_type, nodes, servers_by_id, topology_metadata_json))

        if topology_type == TopologyType.PROXY_MULTI_EXIT:
            if len(proxy_nodes) != 1:
                errors.append("Proxy-multi-exit topology must contain exactly one proxy node")
            if len(exit_nodes) < 1:
                errors.append("Proxy-multi-exit topology must contain at least one exit node")
            if standard_nodes:
                errors.append("Proxy-multi-exit topology cannot contain standard-vpn nodes")
            exit_server_ids = {node.server_id for node in exit_nodes}
            if default_exit_server_id and default_exit_server_id not in exit_server_ids:
                errors.append("Default exit server must be one of the topology exit nodes")
            proxy_node = proxy_nodes[0] if len(proxy_nodes) == 1 else None
            if proxy_node and clients:
                for client in clients:
                    if client.archived or client.server_id != proxy_node.server_id:
                        continue
                    if client.exit_server_id and client.exit_server_id not in exit_server_ids:
                        errors.append(
                            f"Client {client.name} points to exit server #{client.exit_server_id}, but that server is not attached as an exit in this topology."
                        )
            if not errors:
                errors.extend(self._proxy_exit_overlap_errors(topology_type, nodes, servers_by_id, topology_metadata_json))

        if secondary_proxy_nodes:
            warnings.append("proxy-secondary nodes are reserved for future HA logic and are not active in v1")

        if exit_nodes:
            priorities = [node.priority for node in exit_nodes]
            if len(priorities) != len(set(priorities)):
                errors.append("Exit node priorities must be unique within a topology")

        if not nodes:
            warnings.append("Topology has no nodes attached yet")

        return TopologyValidationResult(topology_id=topology_id, errors=errors, warnings=warnings)
