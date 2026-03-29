from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import shlex
from datetime import UTC, datetime

from app.models.client import Client
from app.models.server import Server, ServerRole
from app.models.topology import Topology, TopologyType
from app.models.topology_node import TopologyNode, TopologyNodeRole
from app.services.bootstrap_commands import wrap_with_optional_sudo
from app.services.server_credentials import ServerCredentialsService
from app.services.ssh import SSHService
from app.services.standard_config_adopter import StandardConfigAdopter
from app.services.topology_renderer import RenderedConfig, TopologyRenderer

KEYPAIR_COMMAND = r"""
set -e
if command -v awg >/dev/null 2>&1; then
  priv=$(awg genkey)
  pub=$(printf %s "$priv" | awg pubkey)
elif command -v wg >/dev/null 2>&1; then
  priv=$(wg genkey)
  pub=$(printf %s "$priv" | wg pubkey)
else
  exit 44
fi
printf '{"private":"%s","public":"%s"}\n' "$priv" "$pub"
""".strip()

SSH_PREPARE_TIMEOUT_SECONDS = 120.0
SSH_APPLY_TIMEOUT_SECONDS = 300.0


class TopologyDeployer:
    # Orchestrates the first real "apply topology" flow: keys, config upload, and interface bring-up.
    def __init__(self) -> None:
        self.ssh = SSHService()
        self.credentials = ServerCredentialsService()
        self.adopter = StandardConfigAdopter()

    def _extract_config_value(self, content: str, key: str) -> str | None:
        match = re.search(rf"^{re.escape(key)}\s*=\s*(.+)$", content, re.MULTILINE)
        return match.group(1).strip() if match else None

    def _docker_container_name(self, server: Server) -> str | None:
        if server.live_runtime_details_json:
            try:
                runtime_details = json.loads(server.live_runtime_details_json)
            except json.JSONDecodeError:
                runtime_details = {}
            docker_container = runtime_details.get("docker_container")
            if isinstance(docker_container, str) and docker_container.strip():
                return docker_container.strip()
        if getattr(server.install_method, "value", None) == "docker":
            return "amnezia-awg"
        return None

    def _representative_client_ip(self, subnet: str, interface_address: str | None) -> str:
        network = ipaddress.ip_network(subnet, strict=False)
        interface_ip = None
        if interface_address:
            try:
                interface_ip = ipaddress.ip_interface(interface_address).ip
            except ValueError:
                interface_ip = None

        for host in network.hosts():
            if interface_ip is not None and host == interface_ip:
                continue
            return str(host)
        raise RuntimeError(f"No representative client IP available in subnet {subnet}")

    def _should_manage_proxy_exit_exit_nat(self, config: RenderedConfig) -> bool:
        if not config.metadata or config.metadata.get("proxy_exit_role") != "exit":
            return False
        return config.metadata.get("preserve_existing") != "1"

    def _build_native_nat_commands(self, server: Server, config: RenderedConfig) -> list[str]:
        network_cidr = None
        if config.metadata and config.metadata.get("proxy_exit_role"):
            if not self._should_manage_proxy_exit_exit_nat(config):
                return []
            network_cidr = config.metadata.get("proxy_client_subnet")
        elif server.role == ServerRole.STANDARD_VPN:
            address = self._extract_config_value(config.content, "Address")
            if address:
                try:
                    network_cidr = str(ipaddress.ip_interface(address).network)
                except ValueError:
                    network_cidr = None
        if not network_cidr:
            return []

        interface = shlex.quote(config.interface_name)
        network = shlex.quote(str(network_cidr))
        return [
            'UPLINK_IFACE="$(ip route show default 2>/dev/null | awk \'/default/ {print $5; exit}\')"',
            'if [ -z "${UPLINK_IFACE:-}" ]; then UPLINK_IFACE="$(ip -o route get 1.1.1.1 2>/dev/null | awk \'{for(i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}\')"; fi',
            f'if command -v iptables >/dev/null 2>&1 && [ -n "${{UPLINK_IFACE:-}}" ]; then iptables -t nat -C POSTROUTING -s {network} -o "$UPLINK_IFACE" -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -s {network} -o "$UPLINK_IFACE" -j MASQUERADE; fi',
            f'if command -v iptables >/dev/null 2>&1; then iptables -C FORWARD -i {interface} -j ACCEPT 2>/dev/null || iptables -A FORWARD -i {interface} -j ACCEPT; fi',
            f'if command -v iptables >/dev/null 2>&1; then iptables -C FORWARD -o {interface} -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || iptables -A FORWARD -o {interface} -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT; fi',
        ]

    def _build_proxy_exit_proxy_routing_commands(self, config: RenderedConfig) -> list[str]:
        if not config.metadata or config.metadata.get("proxy_exit_role") != "proxy":
            return []
        subnet = config.metadata.get("proxy_client_subnet")
        if not subnet:
            return []
        interface = shlex.quote(config.interface_name)
        table_id = shlex.quote(config.metadata.get("proxy_service_table_id") or "51820")
        return [
            f'while ip rule show | grep -Fq "from {subnet} "; do ip rule del from {shlex.quote(subnet)} || break; done',
            f'ip route flush table {table_id} || true',
            f'ip rule add from {shlex.quote(subnet)} table {table_id}',
            f'ip route replace {shlex.quote(subnet)} dev {interface} table {table_id}',
            f'ip route replace default dev {interface} scope link table {table_id}',
        ]

    def _build_proxy_exit_proxy_cleanup_commands(self, config: RenderedConfig) -> list[str]:
        if not config.metadata or config.metadata.get("proxy_exit_role") != "proxy":
            return []
        subnet = config.metadata.get("proxy_client_subnet")
        if not subnet:
            return []
        return [
            (
                "if command -v iptables >/dev/null 2>&1; then "
                'for IFACE in $(ip -o link show 2>/dev/null | awk -F": " \'{print $2}\' | cut -d"@" -f1); do '
                '[ -n "$IFACE" ] || continue; '
                f'while iptables -t nat -C POSTROUTING -s {subnet} -o "$IFACE" -j MASQUERADE >/dev/null 2>&1; do '
                f'iptables -t nat -D POSTROUTING -s {subnet} -o "$IFACE" -j MASQUERADE >/dev/null 2>&1 || break; '
                "done; "
                "done; "
                "fi"
            ),
        ]

    def _docker_client_network(self, server: Server, config: RenderedConfig) -> str | None:
        if config.metadata and config.metadata.get("proxy_exit_role"):
            if not self._should_manage_proxy_exit_exit_nat(config):
                return None
            return config.metadata.get("proxy_client_subnet")
        if server.role != ServerRole.STANDARD_VPN:
            return None

        address = self._extract_config_value(config.content, "Address")
        if not address:
            return None

        try:
            return str(ipaddress.ip_interface(address).network)
        except ValueError:
            return None

    def _build_docker_host_firewall_commands(self) -> list[str]:
        return [
            "sysctl -w net.ipv4.ip_forward=1",
            "iptables -C FORWARD -j DOCKER-USER 2>/dev/null || iptables -A FORWARD -j DOCKER-USER",
            "iptables -C FORWARD -j DOCKER-ISOLATION-STAGE-1 2>/dev/null || iptables -A FORWARD -j DOCKER-ISOLATION-STAGE-1",
            "iptables -C FORWARD -o amn0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || iptables -A FORWARD -o amn0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT",
            "iptables -C FORWARD -i amn0 ! -o amn0 -j ACCEPT 2>/dev/null || iptables -A FORWARD -i amn0 ! -o amn0 -j ACCEPT",
            "iptables -C FORWARD -i amn0 -o amn0 -j ACCEPT 2>/dev/null || iptables -A FORWARD -i amn0 -o amn0 -j ACCEPT",
            "iptables -C FORWARD -o docker0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || iptables -A FORWARD -o docker0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT",
            "iptables -C FORWARD -o docker0 -j DOCKER 2>/dev/null || iptables -A FORWARD -o docker0 -j DOCKER",
            "iptables -C FORWARD -i docker0 ! -o docker0 -j ACCEPT 2>/dev/null || iptables -A FORWARD -i docker0 ! -o docker0 -j ACCEPT",
            "iptables -C FORWARD -i docker0 -o docker0 -j ACCEPT 2>/dev/null || iptables -A FORWARD -i docker0 -o docker0 -j ACCEPT",
        ]

    def _build_docker_container_nat_commands(self, server: Server, config: RenderedConfig) -> list[str]:
        network_cidr = self._docker_client_network(server, config)
        if not network_cidr:
            return []

        interface = shlex.quote(config.interface_name)
        network = shlex.quote(network_cidr)
        return [
            "sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true",
            f"iptables -C INPUT -i {interface} -j ACCEPT 2>/dev/null || iptables -A INPUT -i {interface} -j ACCEPT",
            f"iptables -C FORWARD -i {interface} -j ACCEPT 2>/dev/null || iptables -A FORWARD -i {interface} -j ACCEPT",
            f"iptables -C OUTPUT -o {interface} -j ACCEPT 2>/dev/null || iptables -A OUTPUT -o {interface} -j ACCEPT",
            "iptables -C FORWARD -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || iptables -A FORWARD -m state --state ESTABLISHED,RELATED -j ACCEPT",
            f'for IFACE in eth0 eth1; do ip link show "$IFACE" >/dev/null 2>&1 || continue; iptables -C FORWARD -i {interface} -o "$IFACE" -s {network} -j ACCEPT 2>/dev/null || iptables -A FORWARD -i {interface} -o "$IFACE" -s {network} -j ACCEPT; iptables -t nat -C POSTROUTING -s {network} -o "$IFACE" -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -s {network} -o "$IFACE" -j MASQUERADE; done',
        ]

    async def generate_keypair(self, server: Server) -> tuple[str, str]:
        command = KEYPAIR_COMMAND
        docker_container = None
        if server.live_runtime_details_json:
            try:
                docker_container = json.loads(server.live_runtime_details_json).get("docker_container")
            except json.JSONDecodeError:
                docker_container = None
        if server.install_method.value == "docker" or docker_container:
            container_name = shlex.quote(str(docker_container or "amnezia-awg"))
            command = f"docker exec {container_name} sh -lc {shlex.quote(KEYPAIR_COMMAND)}"

        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=self.credentials.get_ssh_password(server),
            private_key=self.credentials.get_private_key(server),
            command=command,
        )
        if result.exit_status != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to generate AWG keypair")
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        return payload["private"], payload["public"]

    async def upload_and_apply(self, server: Server, config: RenderedConfig) -> None:
        password = self.credentials.get_ssh_password(server)
        private_key = self.credentials.get_private_key(server)
        sudo_password = self.credentials.get_sudo_password(server)
        docker_container = None
        if server.live_runtime_details_json:
            try:
                docker_container = json.loads(server.live_runtime_details_json).get("docker_container")
            except json.JSONDecodeError:
                docker_container = None
        directory = shlex.quote("/etc/amnezia/amneziawg")
        remote_path = shlex.quote(config.remote_path)
        interface = shlex.quote(config.interface_name)

        if server.install_method.value == "docker" or docker_container:
            container_name = shlex.quote(str(docker_container or "amnezia-awg"))
            remote_dir = shlex.quote(str(config.remote_path.rsplit("/", 1)[0] if "/" in config.remote_path else "/opt/amnezia/awg"))
            container_path = shlex.quote(config.remote_path)
            container_interface = shlex.quote(config.interface_name)
            docker_inner_steps = [
                f"mkdir -p {remote_dir}",
                f"chmod 600 {container_path} 2>/dev/null || true",
                (
                    f"if command -v wg >/dev/null 2>&1 && command -v wg-quick >/dev/null 2>&1; then "
                    f"(wg-quick down {container_path} || true) && wg-quick up {container_path}; "
                    f"elif command -v awg >/dev/null 2>&1 && command -v awg-quick >/dev/null 2>&1; then "
                    f"(awg-quick down {container_path} || true) && awg-quick up {container_path}; "
                    f"else exit 44; fi"
                ),
                *self._build_docker_container_nat_commands(server, config),
            ]
            host_steps = [
                "set -e",
                *self._build_docker_host_firewall_commands(),
                *self._build_proxy_exit_proxy_cleanup_commands(config),
                *self._build_proxy_exit_proxy_routing_commands(config),
                f"docker exec {container_name} sh -lc 'mkdir -p {remote_dir}'",
                f"docker cp /tmp/{config.interface_name}.conf {container_name}:{container_path}",
                f"docker exec {container_name} sh -lc {shlex.quote(' && '.join(docker_inner_steps))}",
                f"rm -f /tmp/{config.interface_name}.conf",
            ]
            prepare_command = wrap_with_optional_sudo(
                " && ".join(host_steps),
                sudo_password,
            )
            await self.ssh.upload_text_file(
                host=server.host,
                username=server.ssh_user,
                port=server.ssh_port,
                password=password,
                private_key=private_key,
                remote_path=f"/tmp/{config.interface_name}.conf",
                content=config.content,
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
                raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to apply docker config")
            return

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
            timeout_seconds=SSH_PREPARE_TIMEOUT_SECONDS,
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
                    *self._build_proxy_exit_proxy_cleanup_commands(config),
                    *self._build_native_nat_commands(server, config),
                    *self._build_proxy_exit_proxy_routing_commands(config),
                ]
            ),
            sudo_password,
        )
        try:
            result = await self.ssh.run_command(
                host=server.host,
                username=server.ssh_user,
                port=server.ssh_port,
                password=password,
                private_key=private_key,
                command=apply_command,
                timeout_seconds=SSH_APPLY_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise RuntimeError(
                f"Timed out while applying {config.interface_name} on {server.name} ({server.host})"
            ) from exc
        if result.exit_status != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to apply config")

    async def upload_and_apply_adopted_standard(
        self,
        server: Server,
        config: RenderedConfig,
    ) -> None:
        password = self.credentials.get_ssh_password(server)
        private_key = self.credentials.get_private_key(server)
        sudo_password = self.credentials.get_sudo_password(server)
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
            container_path = shlex.quote(config.remote_path)
            container_interface = shlex.quote(config.interface_name)
            docker_inner_steps = [
                f"chmod 600 {container_path} 2>/dev/null || true",
                (
                    f"if command -v wg >/dev/null 2>&1 && command -v wg-quick >/dev/null 2>&1; then "
                    f"(wg-quick down {container_path} || true) && wg-quick up {container_path}; "
                    f"elif command -v awg >/dev/null 2>&1 && command -v awg-quick >/dev/null 2>&1; then "
                    f"(awg-quick down {container_path} || true) && awg-quick up {container_path}; "
                    f"else exit 44; fi"
                ),
                *self._build_docker_container_nat_commands(server, config),
                f"if command -v awg >/dev/null 2>&1; then awg show {container_interface} >/dev/null 2>&1 || true; elif command -v wg >/dev/null 2>&1; then wg show {container_interface} >/dev/null 2>&1 || true; fi",
            ]
            host_steps = [
                "set -e",
                *self._build_docker_host_firewall_commands(),
                *self._build_proxy_exit_proxy_cleanup_commands(config),
                *self._build_proxy_exit_proxy_routing_commands(config),
                f"docker exec {shlex.quote(docker_container)} sh -lc \"cp {shlex.quote(config.remote_path)} {shlex.quote(config.remote_path)}.bak.{backup_suffix} 2>/dev/null || true\"",
                f"docker cp {shlex.quote(temp_remote)} {shlex.quote(docker_container)}:{shlex.quote(config.remote_path)}",
                f"docker exec {shlex.quote(docker_container)} sh -lc {shlex.quote(' && '.join(docker_inner_steps))}",
                f"rm -f {shlex.quote(temp_remote)}",
            ]
            apply_command = " && ".join(host_steps)
            apply_command = wrap_with_optional_sudo(apply_command, sudo_password)
        else:
            directory = shlex.quote(str(config.remote_path.rsplit('/', 1)[0] if '/' in config.remote_path else "/etc/amnezia/amneziawg"))
            remote_path = shlex.quote(config.remote_path)
            interface = shlex.quote(config.interface_name)
            native_steps = [
                "set -e",
                f"mkdir -p {directory}",
                f"cp {remote_path} {remote_path}.bak.{backup_suffix} 2>/dev/null || true",
                f"mv {shlex.quote(temp_remote)} {remote_path}",
                f"chmod 600 {remote_path}",
                f"(awg-quick down {interface} || wg-quick down {interface} || true)",
                f"(awg-quick up {interface} || wg-quick up {interface})",
                *self._build_proxy_exit_proxy_cleanup_commands(config),
                *self._build_native_nat_commands(server, config),
                *self._build_proxy_exit_proxy_routing_commands(config),
            ]
            apply_command = wrap_with_optional_sudo(
                " && ".join(native_steps),
                sudo_password,
            )

        try:
            result = await self.ssh.run_command(
                host=server.host,
                username=server.ssh_user,
                port=server.ssh_port,
                password=password,
                private_key=private_key,
                command=apply_command,
                timeout_seconds=SSH_APPLY_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise RuntimeError(
                f"Timed out while applying imported config {config.interface_name} on {server.name} ({server.host})"
            ) from exc
        if result.exit_status != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to apply adopted imported config")

    async def verify_proxy_exit_path(self, proxy_server: Server, proxy_config: RenderedConfig, exit_server: Server, exit_config: RenderedConfig) -> None:
        subnet = proxy_config.metadata.get("proxy_client_subnet") if proxy_config.metadata else None
        if not subnet:
            raise RuntimeError("Proxy-exit verification failed: proxy client subnet is missing")
        table_id = proxy_config.metadata.get("proxy_service_table_id") if proxy_config.metadata else None
        if not table_id:
            raise RuntimeError("Proxy-exit verification failed: proxy service table id is missing")

        proxy_interface = shlex.quote(proxy_config.interface_name)
        proxy_peer_check = (
            f'if command -v awg >/dev/null 2>&1; then awg show {proxy_interface} peers | grep -q . || {{ echo "Missing tunnel peer on proxy interface {proxy_config.interface_name}" >&2; exit 43; }}; '
            f'elif command -v wg >/dev/null 2>&1; then wg show {proxy_interface} peers | grep -q . || {{ echo "Missing tunnel peer on proxy interface {proxy_config.interface_name}" >&2; exit 43; }}; '
            'else echo "Neither awg nor wg is available on proxy" >&2; exit 44; fi'
        )
        proxy_container = self._docker_container_name(proxy_server)
        if proxy_container:
            proxy_peer_check = f"docker exec {shlex.quote(proxy_container)} sh -lc {shlex.quote(proxy_peer_check)}"

        proxy_verify_command = "\n".join(
            [
                "set -eu",
                f'ip rule show | grep -F "from {subnet} lookup {table_id}" >/dev/null',
                f'ip route show table {shlex.quote(table_id)} | grep -F "default dev {proxy_config.interface_name}" >/dev/null',
                f'ip route show table {shlex.quote(table_id)} | grep -F "{subnet} dev {proxy_config.interface_name}" >/dev/null',
                proxy_peer_check,
            ]
        )
        proxy_result = await self.ssh.run_command(
            host=proxy_server.host,
            username=proxy_server.ssh_user,
            port=proxy_server.ssh_port,
            password=self.credentials.get_ssh_password(proxy_server),
            private_key=self.credentials.get_private_key(proxy_server),
            command=wrap_with_optional_sudo(proxy_verify_command, self.credentials.get_sudo_password(proxy_server)),
            timeout_seconds=30,
        )
        if proxy_result.exit_status != 0:
            raise RuntimeError(
                proxy_result.stderr.strip()
                or proxy_result.stdout.strip()
                or f"Proxy-exit verification failed on proxy {proxy_server.name} ({proxy_server.host})"
            )

        exit_interface = shlex.quote(exit_config.interface_name)
        require_exit_nat = self._should_manage_proxy_exit_exit_nat(exit_config)
        exit_container = self._docker_container_name(exit_server)
        if exit_container:
            exit_inner_lines = ["set -eu"]
            if require_exit_nat:
                exit_inner_lines.append(
                    f'if ! iptables-save -t nat | grep -F -- "-A POSTROUTING -s {subnet} -o eth0 -j MASQUERADE" >/dev/null && ! iptables-save -t nat | grep -F -- "-A POSTROUTING -s {subnet} -o eth1 -j MASQUERADE" >/dev/null; then echo "Missing MASQUERADE for {subnet} via eth0/eth1 on docker exit" >&2; exit 42; fi'
                )
            exit_inner_lines.append(
                f'if command -v awg >/dev/null 2>&1; then awg show {exit_interface} peers | grep -q . || {{ echo "Missing tunnel peer on exit interface {exit_config.interface_name}" >&2; exit 43; }}; elif command -v wg >/dev/null 2>&1; then wg show {exit_interface} peers | grep -q . || {{ echo "Missing tunnel peer on exit interface {exit_config.interface_name}" >&2; exit 43; }}; else echo "Neither awg nor wg is available on exit" >&2; exit 44; fi'
            )
            exit_inner_verify = "\n".join(exit_inner_lines)
            exit_verify_command = "\n".join(
                [
                    "set -eu",
                    f"docker exec {shlex.quote(exit_container)} sh -lc {shlex.quote(exit_inner_verify)}",
                ]
            )
        else:
            exit_lines = [
                "set -eu",
                'UPLINK_IFACE="$(ip route show default 2>/dev/null | awk \'/default/ {print $5; exit}\')"',
                'if [ -z "${UPLINK_IFACE:-}" ]; then UPLINK_IFACE="$(ip -o route get 1.1.1.1 2>/dev/null | awk \'{for(i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}\')"; fi',
                'if [ -z "${UPLINK_IFACE:-}" ]; then echo "Missing exit uplink interface" >&2; exit 41; fi',
            ]
            if require_exit_nat:
                exit_lines.append(
                    f'if ! iptables-save -t nat | grep -F -- "-A POSTROUTING -s {subnet} -o " | grep -F -- " -j MASQUERADE" | grep -F -- " -o $UPLINK_IFACE " >/dev/null; then echo "Missing MASQUERADE for {subnet} via $UPLINK_IFACE on exit" >&2; exit 42; fi'
                )
            exit_lines.append(
                f'if command -v awg >/dev/null 2>&1; then awg show {exit_interface} peers | grep -q . || {{ echo "Missing tunnel peer on exit interface {exit_config.interface_name}" >&2; exit 43; }}; elif command -v wg >/dev/null 2>&1; then wg show {exit_interface} peers | grep -q . || {{ echo "Missing tunnel peer on exit interface {exit_config.interface_name}" >&2; exit 43; }}; else echo "Neither awg nor wg is available on exit" >&2; exit 44; fi'
            )
            exit_verify_command = "\n".join(exit_lines)
        exit_result = await self.ssh.run_command(
            host=exit_server.host,
            username=exit_server.ssh_user,
            port=exit_server.ssh_port,
            password=self.credentials.get_ssh_password(exit_server),
            private_key=self.credentials.get_private_key(exit_server),
            command=wrap_with_optional_sudo(exit_verify_command, self.credentials.get_sudo_password(exit_server)),
            timeout_seconds=30,
        )
        if exit_result.exit_status != 0:
            raise RuntimeError(
                exit_result.stderr.strip()
                or exit_result.stdout.strip()
                or f"Proxy-exit verification failed on exit {exit_server.name} ({exit_server.host})"
            )

    async def deploy(
        self,
        topology: Topology,
        nodes: list[TopologyNode],
        servers_by_id: dict[int, Server],
        clients: list[Client] | None = None,
        progress_callback: callable | None = None,
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
        elif topology.type == TopologyType.PROXY_EXIT:
            # Render synchronously after preparing real keys.
            proxy_node = next((item for item in nodes if item.role == TopologyNodeRole.PROXY), None)
            if not proxy_node:
                raise RuntimeError("Proxy-exit topology must contain exactly one proxy node")

            exit_nodes = sorted(
                [item for item in nodes if item.role == TopologyNodeRole.EXIT],
                key=lambda item: item.priority,
            )
            if not exit_nodes:
                raise RuntimeError("Proxy-exit topology must contain at least one exit node")

            for node in exit_nodes:
                proxy_server = servers_by_id[proxy_node.server_id]
                exit_server = servers_by_id[node.server_id]
                interface_name = f"awg{node.priority}"
                proxy_private, proxy_public, exit_private, exit_public = await key_provider(
                    proxy_server.id,
                    exit_server.id,
                    interface_name,
                )
                proxy_main_private, proxy_main_public, _unused_exit_private, _unused_exit_public = await key_provider(
                    proxy_server.id,
                    proxy_server.id,
                    "awg0",
                )
                keypairs_by_scope = {
                    (proxy_server.id, exit_server.id, interface_name): (proxy_private, proxy_public, exit_private, exit_public),
                    (proxy_server.id, proxy_server.id, "awg0"): (proxy_main_private, proxy_main_public, "", ""),
                }
                rendered.extend(
                    renderer.render(
                        topology,
                        [proxy_node, node],
                        {proxy_server.id: proxy_server, exit_server.id: exit_server},
                        key_provider=lambda proxy_id, exit_id, iface_name, _keypairs=keypairs_by_scope: _keypairs[(proxy_id, exit_id, iface_name)],
                    )
                )

            proxy_server = servers_by_id[proxy_node.server_id]
            proxy_runtime = {}
            if getattr(proxy_server, "live_runtime_details_json", None):
                try:
                    proxy_runtime = json.loads(proxy_server.live_runtime_details_json)
                except json.JSONDecodeError:
                    proxy_runtime = {}
            proxy_live_config = proxy_runtime.get("config_preview") if isinstance(proxy_runtime, dict) else None
            proxy_live_interface = getattr(proxy_server, "live_interface_name", None) or "awg0"
            proxy_live_config_path = getattr(proxy_server, "live_config_path", None)
            if (
                isinstance(proxy_live_config, str)
                and "# service-exit-peer" in proxy_live_config
                and proxy_live_config_path
                and all(item.interface_name != proxy_live_interface for item in rendered)
            ):
                cleaned_proxy_content = self.adopter.remove_service_peer(proxy_live_config)
                if cleaned_proxy_content != proxy_live_config:
                    rendered.insert(
                        0,
                        RenderedConfig(
                            server_id=proxy_server.id,
                            interface_name=proxy_live_interface,
                            remote_path=proxy_live_config_path,
                            content=cleaned_proxy_content,
                            metadata={"preserve_existing": "1"},
                        ),
                    )
        else:
            raise RuntimeError(f"Unsupported topology type for deploy: {topology.type.value}")

        for config in rendered:
            server = servers_by_id[config.server_id]
            if progress_callback:
                progress_callback(
                    f"Applying {config.interface_name} on {server.name} ({server.host})"
                )
            if not server.awg_detected:
                raise RuntimeError(f"AWG runtime not detected on server {server.name}")
            if (topology.type == TopologyType.STANDARD and server.config_source == "imported") or (
                config.metadata and config.metadata.get("preserve_existing") == "1"
            ):
                await self.upload_and_apply_adopted_standard(server, config)
            else:
                await self.upload_and_apply(server, config)

        if topology.type == TopologyType.PROXY_EXIT:
            proxy_config = next(
                (item for item in rendered if item.metadata and item.metadata.get("proxy_exit_role") == "proxy"),
                None,
            )
            exit_config = next(
                (item for item in rendered if item.metadata and item.metadata.get("proxy_exit_role") == "exit"),
                None,
            )
            if not proxy_config or not exit_config:
                raise RuntimeError("Proxy-exit verification failed: rendered proxy/exit configs are incomplete")
            await self.verify_proxy_exit_path(
                servers_by_id[proxy_config.server_id],
                proxy_config,
                servers_by_id[exit_config.server_id],
                exit_config,
            )

        return rendered


def deploy_topology_sync(
    topology: Topology,
    nodes: list[TopologyNode],
    servers_by_id: dict[int, Server],
    clients: list[Client] | None = None,
    progress_callback: callable | None = None,
) -> list[RenderedConfig]:
    # Worker entrypoint uses a sync wrapper around the async SSH deploy orchestration.
    return asyncio.run(TopologyDeployer().deploy(topology, nodes, servers_by_id, clients, progress_callback))
