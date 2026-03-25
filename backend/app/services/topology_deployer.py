from __future__ import annotations

import asyncio
import json
import shlex
from datetime import UTC, datetime

from app.models.client import Client
from app.models.server import Server
from app.models.topology import Topology, TopologyType
from app.models.topology_node import TopologyNode, TopologyNodeRole
from app.services.bootstrap_commands import wrap_with_optional_sudo
from app.services.server_credentials import ServerCredentialsService
from app.services.ssh import SSHService
from app.services.standard_config_adopter import StandardConfigAdopter
from app.services.topology_renderer import RenderedConfig, TopologyRenderer

KEYPAIR_COMMAND = r"""
set -e
priv=$(awg genkey)
pub=$(printf %s "$priv" | awg pubkey)
printf '{"private":"%s","public":"%s"}\n' "$priv" "$pub"
""".strip()


class TopologyDeployer:
    # Orchestrates the first real "apply topology" flow: keys, config upload, and interface bring-up.
    def __init__(self) -> None:
        self.ssh = SSHService()
        self.credentials = ServerCredentialsService()
        self.adopter = StandardConfigAdopter()

    async def generate_keypair(self, server: Server) -> tuple[str, str]:
        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=self.credentials.get_ssh_password(server),
            private_key=self.credentials.get_private_key(server),
            command=KEYPAIR_COMMAND,
        )
        if result.exit_status != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to generate AWG keypair")
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        return payload["private"], payload["public"]

    async def upload_and_apply(self, server: Server, config: RenderedConfig) -> None:
        password = self.credentials.get_ssh_password(server)
        private_key = self.credentials.get_private_key(server)
        sudo_password = self.credentials.get_sudo_password(server)
        directory = shlex.quote("/etc/amnezia/amneziawg")
        remote_path = shlex.quote(config.remote_path)
        interface = shlex.quote(config.interface_name)

        prepare_command = wrap_with_optional_sudo(
            f"mkdir -p {directory} && chmod 700 {directory}",
            sudo_password,
        )
        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            command=prepare_command,
        )
        if result.exit_status != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to prepare config directory")

        await self.ssh.upload_text_file(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            remote_path=f"/tmp/{config.interface_name}.conf",
            content=config.content,
        )

        # We stage through /tmp first because the final config path usually requires elevated permissions.
        apply_command = wrap_with_optional_sudo(
            " && ".join(
                [
                    f"mv /tmp/{config.interface_name}.conf {remote_path}",
                    f"chmod 600 {remote_path}",
                    "sysctl -w net.ipv4.ip_forward=1",
                    f"awg-quick down {interface} || true",
                    f"awg-quick up {interface}",
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
            command=apply_command,
        )
        if result.exit_status != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to apply config")

    async def upload_and_apply_adopted_standard(
        self,
        server: Server,
        config: RenderedConfig,
    ) -> None:
        password = self.credentials.get_ssh_password(server)
        private_key = self.credentials.get_private_key(server)
        docker_container = None
        if server.live_runtime_details_json:
            try:
                docker_container = json.loads(server.live_runtime_details_json).get("docker_container")
            except json.JSONDecodeError:
                docker_container = None

        if not config.remote_path:
            raise RuntimeError("Imported standard config path is missing")

        temp_remote = f"/tmp/{config.interface_name}.conf"
        await self.ssh.upload_text_file(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            remote_path=temp_remote,
            content=config.content,
        )

        backup_suffix = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        if docker_container:
            apply_command = (
                "set -e && "
                f"docker exec {shlex.quote(docker_container)} sh -lc "
                f"\"cp {shlex.quote(config.remote_path)} {shlex.quote(config.remote_path)}.bak.{backup_suffix} 2>/dev/null || true\" && "
                f"docker cp {shlex.quote(temp_remote)} {shlex.quote(docker_container)}:{shlex.quote(config.remote_path)} && "
                f"docker exec {shlex.quote(docker_container)} sh -lc "
                f"\"if command -v wg >/dev/null 2>&1 && command -v wg-quick >/dev/null 2>&1; then "
                f"tmp=$(mktemp) && wg-quick strip {shlex.quote(config.remote_path)} > \\\"$tmp\\\" && wg syncconf {shlex.quote(config.interface_name)} \\\"$tmp\\\" && rm -f \\\"$tmp\\\"; "
                f"elif command -v awg >/dev/null 2>&1 && command -v awg-quick >/dev/null 2>&1; then "
                f"tmp=$(mktemp) && awg-quick strip {shlex.quote(config.remote_path)} > \\\"$tmp\\\" && awg syncconf {shlex.quote(config.interface_name)} \\\"$tmp\\\" && rm -f \\\"$tmp\\\"; "
                f"else exit 44; fi\" || docker restart {shlex.quote(docker_container)} && "
                f"rm -f {shlex.quote(temp_remote)}"
            )
        else:
            directory = shlex.quote(str(config.remote_path.rsplit('/', 1)[0] if '/' in config.remote_path else "/etc/amnezia/amneziawg"))
            remote_path = shlex.quote(config.remote_path)
            interface = shlex.quote(config.interface_name)
            apply_command = (
                "set -e && "
                f"mkdir -p {directory} && "
                f"cp {remote_path} {remote_path}.bak.{backup_suffix} 2>/dev/null || true && "
                f"mv {shlex.quote(temp_remote)} {remote_path} && "
                f"chmod 600 {remote_path} && "
                f"(awg-quick down {interface} || wg-quick down {interface} || true) && "
                f"(awg-quick up {interface} || wg-quick up {interface})"
            )

        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=password,
            private_key=private_key,
            command=apply_command,
        )
        if result.exit_status != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to apply adopted imported config")

    async def deploy(
        self,
        topology: Topology,
        nodes: list[TopologyNode],
        servers_by_id: dict[int, Server],
        clients: list[Client] | None = None,
    ) -> list[RenderedConfig]:
        key_cache: dict[tuple[int, int, str], tuple[str, str, str, str]] = {}

        async def key_provider(proxy_id: int, exit_id: int, interface_name: str) -> tuple[str, str, str, str]:
            cache_key = (proxy_id, exit_id, interface_name)
            if cache_key not in key_cache:
                proxy_private, proxy_public = await self.generate_keypair(servers_by_id[proxy_id])
                exit_private, exit_public = await self.generate_keypair(servers_by_id[exit_id])
                key_cache[cache_key] = (proxy_private, proxy_public, exit_private, exit_public)
            return key_cache[cache_key]

        renderer = TopologyRenderer()
        rendered: list[RenderedConfig] = []
        if topology.type == TopologyType.STANDARD:
            standard_node = next((item for item in nodes if item.role == TopologyNodeRole.STANDARD_VPN), None)
            if not standard_node:
                raise RuntimeError("Standard topology must contain a standard-vpn node")

            standard_server = servers_by_id[standard_node.server_id]
            if standard_server.config_source == "imported":
                runtime_details = {}
                if standard_server.live_runtime_details_json:
                    try:
                        runtime_details = json.loads(standard_server.live_runtime_details_json)
                    except json.JSONDecodeError:
                        runtime_details = {}
                live_config = runtime_details.get("config_preview") or ""
                if not isinstance(live_config, str) or not live_config.strip():
                    raise RuntimeError("Imported standard topology is missing live wg0.conf content")
                if not standard_server.live_config_path:
                    raise RuntimeError("Imported standard topology is missing config path")
                topology_clients = [
                    client
                    for client in (clients or [])
                    if client.server_id == standard_server.id and client.topology_id == topology.id
                ]
                if not topology_clients:
                    topology_clients = [client for client in (clients or []) if client.server_id == standard_server.id]
                merged_content = self.adopter.render(standard_server, topology_clients, live_config)
                rendered = [
                    RenderedConfig(
                        server_id=standard_server.id,
                        interface_name=standard_server.live_interface_name or "wg0",
                        remote_path=standard_server.live_config_path,
                        content=merged_content,
                    )
                ]
            else:
                standard_private, _standard_public = await self.generate_keypair(standard_server)
                rendered = renderer.render(
                    topology,
                    [standard_node],
                    {standard_server.id: standard_server},
                    key_provider=lambda *_args: (standard_private, "", "", ""),
                )
        else:
            # Render synchronously after preparing real keys.
            for node in sorted([item for item in nodes if item.role.value == "exit"], key=lambda item: item.priority):
                proxy_node = next(item for item in nodes if item.role.value == "proxy")
                proxy_server = servers_by_id[proxy_node.server_id]
                exit_server = servers_by_id[node.server_id]
                interface_name = f"awg{node.priority}"
                proxy_private, proxy_public, exit_private, exit_public = await key_provider(
                    proxy_server.id,
                    exit_server.id,
                    interface_name,
                )
                rendered.extend(
                    renderer.render(
                        topology,
                        [proxy_node, node],
                        {proxy_server.id: proxy_server, exit_server.id: exit_server},
                        key_provider=lambda *_args: (proxy_private, proxy_public, exit_private, exit_public),
                    )
                )

        for config in rendered:
            server = servers_by_id[config.server_id]
            if not server.awg_detected:
                raise RuntimeError(f"AWG runtime not detected on server {server.name}")
            if topology.type == TopologyType.STANDARD and server.config_source == "imported":
                await self.upload_and_apply_adopted_standard(server, config)
            else:
                await self.upload_and_apply(server, config)

        return rendered


def deploy_topology_sync(
    topology: Topology,
    nodes: list[TopologyNode],
    servers_by_id: dict[int, Server],
    clients: list[Client] | None = None,
) -> list[RenderedConfig]:
    # Worker entrypoint uses a sync wrapper around the async SSH deploy orchestration.
    return asyncio.run(TopologyDeployer().deploy(topology, nodes, servers_by_id, clients))
