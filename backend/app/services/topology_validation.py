from __future__ import annotations

from app.models.topology import TopologyType
from app.models.topology_node import TopologyNode, TopologyNodeRole


class TopologyValidationResult:
    def __init__(self, *, topology_id: int, errors: list[str], warnings: list[str]) -> None:
        self.topology_id = topology_id
        self.errors = errors
        self.warnings = warnings

    @property
    def is_valid(self) -> bool:
        return not self.errors


class TopologyValidationService:
    def validate(self, topology_id: int, topology_type: TopologyType, nodes: list[TopologyNode]) -> TopologyValidationResult:
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

        if topology_type == TopologyType.PROXY_MULTI_EXIT:
            errors.append("Proxy-multi-exit topology is reserved for a future release and is not supported yet")

        if secondary_proxy_nodes:
            warnings.append("proxy-secondary nodes are reserved for future HA logic and are not active in v1")

        if exit_nodes:
            priorities = [node.priority for node in exit_nodes]
            if len(priorities) != len(set(priorities)):
                errors.append("Exit node priorities must be unique within a topology")

        if not nodes:
            warnings.append("Topology has no nodes attached yet")

        return TopologyValidationResult(topology_id=topology_id, errors=errors, warnings=warnings)
