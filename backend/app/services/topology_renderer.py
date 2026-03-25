from __future__ import annotations

import base64
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import x25519

from app.models.topology import Topology, TopologyType
from app.models.topology_node import TopologyNode, TopologyNodeRole
from app.services.awg_profile import AWGProfileService
from app.services.awg_templates import render_link_config, render_standard_server_config


class TopologyRenderError(RuntimeError):
    pass


@dataclass
class RenderedConfig:
    server_id: int
    interface_name: str
    remote_path: str
    content: str


class TopologyRenderer:
    def __init__(self) -> None:
        self.awg_profile = AWGProfileService()

    def _generate_preview_keypair(self) -> tuple[str, str]:
        private = x25519.X25519PrivateKey.generate()
        private_raw = private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_raw = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.b64encode(private_raw).decode("utf-8"), base64.b64encode(public_raw).decode("utf-8")

    def render(
        self,
        topology: Topology,
        nodes: list[TopologyNode],
        servers_by_id: dict[int, object],
        key_provider: callable | None = None,
    ) -> list[RenderedConfig]:
        if topology.type == TopologyType.STANDARD:
            standard_nodes = [node for node in nodes if node.role == TopologyNodeRole.STANDARD_VPN]
            if len(standard_nodes) != 1:
                raise TopologyRenderError("Standard topology must contain exactly one standard-vpn node")

            standard_server = servers_by_id[standard_nodes[0].server_id]
            if getattr(standard_server, "config_source", "generated") == "imported":
                summary = (
                    f"Existing live standard config detected on {standard_server.name}\n"
                    f"Host: {getattr(standard_server, 'host', '-')}\n"
                    f"Interface: {getattr(standard_server, 'live_interface_name', '-') or '-'}\n"
                    f"Address: {getattr(standard_server, 'live_address_cidr', '-') or '-'}\n"
                    f"Listen port: {getattr(standard_server, 'live_listen_port', '-') or '-'}\n"
                    f"Peer count: {getattr(standard_server, 'live_peer_count', '-') or '-'}\n"
                    f"Config source: {getattr(standard_server, 'live_config_path', '-') or '-'}\n"
                    "Preview is showing the imported live summary instead of a replacement template.\n"
                )
                return [
                    RenderedConfig(
                        server_id=standard_server.id,
                        interface_name=getattr(standard_server, "live_interface_name", "awg0") or "awg0",
                        remote_path="/live-summary/imported-standard.txt",
                        content=summary,
                    )
                ]

            if key_provider:
                private_key, *_rest = key_provider(standard_server.id, standard_server.id, "awg0")
            else:
                private_key, _preview_public_key = self._generate_preview_keypair()
            obfuscation_fields = self.awg_profile.for_generated_server(standard_server)

            return [
                RenderedConfig(
                    server_id=standard_server.id,
                    interface_name="awg0",
                    remote_path="/etc/amnezia/amneziawg/awg0.conf",
                    content=render_standard_server_config(
                        topology_name=topology.name,
                        interface_name="awg0",
                        address="10.100.0.1/24",
                        private_key=private_key,
                        extra_interface_fields=obfuscation_fields,
                    ),
                )
            ]

        proxy_nodes = [node for node in nodes if node.role == TopologyNodeRole.PROXY]
        exit_nodes = sorted(
            [node for node in nodes if node.role == TopologyNodeRole.EXIT],
            key=lambda item: item.priority,
        )

        if len(proxy_nodes) != 1:
            raise TopologyRenderError("Topology must contain exactly one proxy node")
        if not exit_nodes:
            raise TopologyRenderError("Topology must contain at least one exit node")

        proxy_server = servers_by_id[proxy_nodes[0].server_id]
        rendered: list[RenderedConfig] = []
        for node in exit_nodes:
            exit_server = servers_by_id[node.server_id]
            interface_name = f"awg{node.priority}"
            proxy_address = f"10.200.{node.priority}.1/30"
            exit_address = f"10.200.{node.priority}.2/30"
            obfuscation_fields = self.awg_profile.for_generated_server(proxy_server)

            if key_provider:
                proxy_private_key, proxy_public_key, exit_private_key, exit_public_key = key_provider(
                    proxy_server.id,
                    exit_server.id,
                    interface_name,
                )
            else:
                proxy_private_key, proxy_public_key = self._generate_preview_keypair()
                exit_private_key, exit_public_key = self._generate_preview_keypair()

            rendered.append(
                RenderedConfig(
                    server_id=proxy_server.id,
                    interface_name=interface_name,
                    remote_path=f"/etc/amnezia/amneziawg/{interface_name}.conf",
                    content=render_link_config(
                        topology_name=topology.name,
                        role="proxy-upstream",
                        interface_name=interface_name,
                        local_address=proxy_address,
                        private_key=proxy_private_key,
                        peer_public_key=exit_public_key,
                        endpoint=f"{exit_server.host}:51820",
                        allowed_ips=f"10.200.{node.priority}.2/32",
                        extra_interface_fields=obfuscation_fields,
                    ),
                )
            )
            rendered.append(
                RenderedConfig(
                    server_id=exit_server.id,
                    interface_name=interface_name,
                    remote_path=f"/etc/amnezia/amneziawg/{interface_name}.conf",
                    content=render_link_config(
                        topology_name=topology.name,
                        role="exit-upstream",
                        interface_name=interface_name,
                        local_address=exit_address,
                        private_key=exit_private_key,
                        peer_public_key=proxy_public_key,
                        endpoint=f"{proxy_server.host}:51820",
                        allowed_ips="10.100.0.0/24,10.200.0.0/16",
                        extra_interface_fields=obfuscation_fields,
                    ),
                )
            )
        return rendered
