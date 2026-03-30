from __future__ import annotations

import base64
import ipaddress
import json
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import x25519

from app.models.topology import Topology, TopologyType
from app.models.topology_node import TopologyNode, TopologyNodeRole
from app.services.awg_profile import AWGProfileService
from app.services.awg_templates import render_link_config, render_standard_server_config
from app.services.standard_config_adopter import StandardConfigAdopter


class TopologyRenderError(RuntimeError):
    pass


@dataclass
class RenderedConfig:
    server_id: int
    interface_name: str
    remote_path: str
    content: str
    metadata: dict[str, str] | None = None


class TopologyRenderer:
    def __init__(self) -> None:
        self.awg_profile = AWGProfileService()
        self.adopter = StandardConfigAdopter()

    def _docker_remote_path(self, server: object, interface_name: str) -> str:
        install_method = getattr(getattr(server, "install_method", None), "value", getattr(server, "install_method", None))
        runtime_details_raw = getattr(server, "live_runtime_details_json", None)
        runtime_details = {}
        if isinstance(runtime_details_raw, str) and runtime_details_raw:
            try:
                runtime_details = json.loads(runtime_details_raw)
            except json.JSONDecodeError:
                runtime_details = {}
        if install_method == "docker" or runtime_details.get("docker_container"):
            return f"/opt/amnezia/awg/{interface_name}.conf"
        return f"/etc/amnezia/amneziawg/{interface_name}.conf"

    def _proxy_client_subnet(self, topology: Topology) -> str:
        try:
            metadata = json.loads(topology.metadata_json) if topology.metadata_json else {}
        except json.JSONDecodeError:
            metadata = {}
        subnet = metadata.get("proxy_client_subnet")
        if isinstance(subnet, str) and subnet.strip():
            return subnet.strip()
        return "10.100.0.0/24"

    def _proxy_interface_address(self, topology: Topology) -> str:
        subnet = self._proxy_client_subnet(topology)
        network = ipaddress.ip_network(subnet, strict=False)
        first_host = next(network.hosts())
        return f"{first_host}/{network.prefixlen}"

    def _proxy_service_interface_name(self, priority: int) -> str:
        # Each exit gets its own service interface on proxy so proxy clients stay on awg0.
        return f"awg{priority}"

    def _proxy_service_interface_address(self, priority: int) -> str:
        return f"10.200.{priority}.1/32"

    def _proxy_service_table_id(self, priority: int) -> str:
        # Routing tables are derived from exit priority to keep per-exit policy routing isolated.
        return str(51820 + priority)

    def _proxy_service_listen_port(self, priority: int) -> int:
        return 51820 + priority

    def _render_service_peer_block(
        self,
        *,
        public_key: str,
        allowed_ips: str,
        endpoint: str | None = None,
        preshared_key: str | None = None,
    ) -> str:
        lines = [
            "[Peer]",
            "# service-exit-peer",
            f"PublicKey = {public_key}",
        ]
        if preshared_key:
            lines.append(f"PresharedKey = {preshared_key}")
        if endpoint:
            lines.append(f"Endpoint = {endpoint}")
        lines.append(f"AllowedIPs = {allowed_ips}")
        lines.append("PersistentKeepalive = 25")
        return "\n".join(lines)

    def _ensure_interface_setting(self, content: str, key: str, value: str) -> str:
        lines = content.splitlines()
        setting_prefix = f"{key} ="
        if any(line.strip().startswith(setting_prefix) for line in lines):
            return content

        insert_index = None
        for index, line in enumerate(lines):
            if line.strip().startswith("[Peer]"):
                insert_index = index
                break
        if insert_index is None:
            lines.append(f"{key} = {value}")
        else:
            lines.insert(insert_index, f"{key} = {value}")
            if insert_index > 0 and lines[insert_index - 1].strip():
                lines.insert(insert_index, "")
        return "\n".join(lines).rstrip() + "\n"

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
            obfuscation_fields = self.awg_profile.for_subject(topology)

            return [
                RenderedConfig(
                    server_id=standard_server.id,
                    interface_name="awg0",
                    remote_path=self._docker_remote_path(standard_server, "awg0"),
                    content=self._ensure_interface_setting(
                        render_standard_server_config(
                            topology_name=topology.name,
                            interface_name="awg0",
                            address="10.100.0.1/24",
                            private_key=private_key,
                            extra_interface_fields=obfuscation_fields,
                        ),
                        "Table",
                        "off",
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
        if topology.type in {TopologyType.PROXY_EXIT, TopologyType.PROXY_MULTI_EXIT}:
            if topology.type == TopologyType.PROXY_EXIT and len(exit_nodes) != 1:
                raise TopologyRenderError("Proxy-exit topology must contain exactly one exit node")
            if topology.type == TopologyType.PROXY_MULTI_EXIT and not exit_nodes:
                raise TopologyRenderError("Proxy-multi-exit topology must contain at least one exit node")

            proxy_subnet = self._proxy_client_subnet(topology)
            proxy_interface_address = self._proxy_interface_address(topology)
            obfuscation_fields = self.awg_profile.for_subject(topology)

            proxy_runtime = {}
            if getattr(proxy_server, "live_runtime_details_json", None):
                try:
                    proxy_runtime = json.loads(proxy_server.live_runtime_details_json)
                except json.JSONDecodeError:
                    proxy_runtime = {}
            proxy_config_preview = proxy_runtime.get("config_preview") if isinstance(proxy_runtime, dict) else None
            proxy_has_live_config = (
                isinstance(proxy_config_preview, str)
                and proxy_config_preview.strip()
                and bool(getattr(proxy_server, "live_config_path", None))
            )

            proxy_main_keypair = key_provider(proxy_server.id, proxy_server.id, "awg0") if key_provider else None
            if proxy_main_keypair:
                proxy_main_private_key = proxy_main_keypair[0]
            else:
                proxy_main_private_key, _proxy_main_public_key = self._generate_preview_keypair()

            rendered: list[RenderedConfig] = []
            if not proxy_has_live_config:
                # Fresh proxy nodes need a real client-facing awg0 before any service tunnels are added.
                proxy_main_content = render_standard_server_config(
                    topology_name=topology.name,
                    interface_name="awg0",
                    address=proxy_interface_address,
                    private_key=proxy_main_private_key,
                    extra_interface_fields=obfuscation_fields,
                ).strip()
                proxy_main_content = self._ensure_interface_setting(proxy_main_content, "Table", "off").strip()
                rendered.append(
                    RenderedConfig(
                        server_id=proxy_server.id,
                        interface_name="awg0",
                        remote_path=self._docker_remote_path(proxy_server, "awg0"),
                        content=proxy_main_content + "\n",
                    )
                )

            for exit_node in exit_nodes:
                exit_server = servers_by_id[exit_node.server_id]
                service_interface_name = self._proxy_service_interface_name(exit_node.priority)
                service_interface_address = self._proxy_service_interface_address(exit_node.priority)
                service_table_id = self._proxy_service_table_id(exit_node.priority)
                service_listen_port = self._proxy_service_listen_port(exit_node.priority)

                exit_runtime = {}
                if getattr(exit_server, "live_runtime_details_json", None):
                    try:
                        exit_runtime = json.loads(exit_server.live_runtime_details_json)
                    except json.JSONDecodeError:
                        exit_runtime = {}

                proxy_keypair = key_provider(proxy_server.id, exit_server.id, service_interface_name) if key_provider else None
                if proxy_keypair:
                    proxy_private_key, proxy_public_key, exit_private_from_provider, exit_public_key = proxy_keypair
                else:
                    proxy_private_key, proxy_public_key = self._generate_preview_keypair()
                    exit_private_from_provider, exit_public_key = self._generate_preview_keypair()

                exit_config_preview = exit_runtime.get("config_preview") if isinstance(exit_runtime, dict) else None
                exit_has_live_config = (
                    isinstance(exit_config_preview, str)
                    and exit_config_preview.strip()
                    and bool(getattr(exit_server, "live_config_path", None))
                )

                exit_private_key = None
                exit_interface_public_key = None
                if isinstance(exit_config_preview, str):
                    for line in exit_config_preview.splitlines():
                        stripped = line.strip()
                        if stripped.startswith("PrivateKey = "):
                            exit_private_key = stripped.split("=", 1)[1].strip()
                            break
                if isinstance(exit_runtime, dict):
                    peers = exit_runtime.get("peers")
                    if isinstance(peers, list):
                        for peer in peers:
                            if not isinstance(peer, dict):
                                continue
                            public_key = peer.get("public_key")
                            allowed_ips = peer.get("allowed_ips")
                            if isinstance(public_key, str) and public_key.strip() and not allowed_ips:
                                exit_interface_public_key = public_key.strip()
                                break
                if not exit_private_key:
                    exit_private_key = exit_private_from_provider
                if exit_has_live_config:
                    exit_public_key = exit_interface_public_key or None
                if not exit_public_key:
                    if exit_private_key:
                        exit_private_raw = base64.b64decode(exit_private_key.encode("utf-8"))
                        exit_private = x25519.X25519PrivateKey.from_private_bytes(exit_private_raw)
                        exit_public_raw = exit_private.public_key().public_bytes(
                            encoding=serialization.Encoding.Raw,
                            format=serialization.PublicFormat.Raw,
                        )
                        exit_public_key = base64.b64encode(exit_public_raw).decode("utf-8")
                    else:
                        _exit_private, exit_public_key = self._generate_preview_keypair()

                exit_endpoint = f"{exit_server.host}:{getattr(exit_server, 'live_listen_port', None) or 51820}"
                proxy_endpoint = f"{proxy_server.host}:{service_listen_port}"
                service_peer_for_exit = self._render_service_peer_block(
                    public_key=proxy_public_key or "",
                    endpoint=proxy_endpoint,
                    allowed_ips=proxy_subnet,
                )

                proxy_content = render_link_config(
                    topology_name=topology.name,
                    role="proxy-exit-service",
                    interface_name=service_interface_name,
                    local_address=service_interface_address,
                    private_key=proxy_private_key or "",
                    peer_public_key=exit_public_key,
                    endpoint=exit_endpoint,
                    allowed_ips="0.0.0.0/0, ::/0",
                    listen_port=service_listen_port,
                    extra_interface_fields=obfuscation_fields,
                ).strip()
                proxy_content = self._ensure_interface_setting(proxy_content, "Table", "off").strip()

                exit_interface_name = getattr(exit_server, "live_interface_name", None) or "awg0"
                exit_remote_path = getattr(exit_server, "live_config_path", None) or self._docker_remote_path(exit_server, exit_interface_name)
                if exit_has_live_config:
                    # Existing exit nodes keep their current awg0 and only receive a topology-owned service peer.
                    exit_content = self.adopter.render_with_service_peer(exit_config_preview, service_peer_for_exit).strip() + "\n"
                    exit_metadata = {"proxy_exit_role": "exit", "proxy_client_subnet": proxy_subnet, "preserve_existing": "1"}
                else:
                    if not exit_private_key:
                        raise TopologyRenderError("Exit server keypair generation failed for proxy topology")
                    exit_content = render_standard_server_config(
                        topology_name=topology.name,
                        interface_name=exit_interface_name,
                        address="10.100.0.1/24",
                        private_key=exit_private_key,
                        extra_interface_fields=obfuscation_fields,
                    ).strip()
                    exit_content = self._ensure_interface_setting(exit_content, "Table", "off").strip()
                    exit_content = self.adopter.render_with_service_peer(exit_content, service_peer_for_exit).strip() + "\n"
                    exit_metadata = {"proxy_exit_role": "exit", "proxy_client_subnet": proxy_subnet}

                rendered.extend(
                    [
                        RenderedConfig(
                            server_id=proxy_server.id,
                            interface_name=service_interface_name,
                            remote_path=self._docker_remote_path(proxy_server, service_interface_name),
                            content=proxy_content + "\n",
                            metadata={
                                "proxy_exit_role": "proxy",
                                "proxy_client_subnet": proxy_subnet,
                                "proxy_service_table_id": service_table_id,
                                "preserve_server_runtime": "1",
                            },
                        ),
                        RenderedConfig(
                            server_id=exit_server.id,
                            interface_name=exit_interface_name,
                            remote_path=exit_remote_path,
                            content=exit_content,
                            metadata=exit_metadata,
                        ),
                    ]
                )
            return rendered

        rendered: list[RenderedConfig] = []
        return rendered
