from __future__ import annotations

from dataclasses import dataclass

from app.core.security import decrypt_value
from app.models.client import Client
from app.models.server import Server


@dataclass
class ParsedPeerBlock:
    public_key: str
    fields: dict[str, str]
    field_order: list[str]
    raw_lines: list[str]


@dataclass
class ParsedConfig:
    interface_lines: list[str]
    interface_fields: dict[str, str]
    peers: list[ParsedPeerBlock]


class StandardConfigAdopter:
    def _policy_comment(self, client: Client) -> str | None:
        if client.manual_disabled:
            return "disabled-manually"
        if client.policy_disabled_reason == "traffic_limit":
            return "disabled-by-traffic-limit"
        if client.policy_disabled_reason == "quiet_hours":
            return "disabled-by-time-policy"
        if client.policy_disabled_reason == "expired":
            return "disabled-by-expiration"
        return None

    def _format_quiet_hours(self, client: Client) -> str | None:
        if client.quiet_hours_start_minute is None or client.quiet_hours_end_minute is None:
            return None
        start_hours = client.quiet_hours_start_minute // 60
        start_minutes = client.quiet_hours_start_minute % 60
        end_hours = client.quiet_hours_end_minute // 60
        end_minutes = client.quiet_hours_end_minute % 60
        timezone = client.quiet_hours_timezone or "UTC"
        return f"{start_hours:02d}:{start_minutes:02d}-{end_hours:02d}:{end_minutes:02d} {timezone}"

    def _client_comment(self, client: Client) -> str:
        parts = [f"client: {client.name}"]
        if client.traffic_limit_mb:
            parts.append(f"limit: {client.traffic_limit_mb} MiB / 30d")
        quiet_hours = self._format_quiet_hours(client)
        if quiet_hours:
            parts.append(f"quiet-hours: {quiet_hours}")
        if client.expires_at:
            parts.append(f"valid-until: {client.expires_at.isoformat()}")
        policy_comment = self._policy_comment(client)
        if policy_comment:
            parts.append(policy_comment)
        return "# " + " | ".join(parts)

    def parse(self, config_text: str) -> ParsedConfig:
        interface_lines: list[str] = []
        interface_fields: dict[str, str] = {}
        peers: list[ParsedPeerBlock] = []
        current_section: str | None = None
        current_peer_lines: list[str] = []

        def flush_peer() -> None:
            nonlocal current_peer_lines
            if not current_peer_lines:
                return
            fields: dict[str, str] = {}
            field_order: list[str] = []
            for line in current_peer_lines:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                normalized_key = key.strip()
                fields[normalized_key] = value.strip()
                field_order.append(normalized_key)
            public_key = fields.get("PublicKey", "")
            peers.append(
                ParsedPeerBlock(
                    public_key=public_key,
                    fields=fields,
                    field_order=field_order,
                    raw_lines=list(current_peer_lines),
                )
            )
            current_peer_lines = []

        for raw_line in config_text.splitlines():
            stripped = raw_line.strip()
            if stripped == "[Interface]":
                flush_peer()
                current_section = "interface"
                interface_lines.append("[Interface]")
                continue
            if stripped == "[Peer]":
                flush_peer()
                current_section = "peer"
                current_peer_lines = ["[Peer]"]
                continue

            if current_section == "interface":
                interface_lines.append(raw_line)
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key, value = stripped.split("=", 1)
                    interface_fields[key.strip()] = value.strip()
            elif current_section == "peer":
                current_peer_lines.append(raw_line)

        flush_peer()
        return ParsedConfig(interface_lines=interface_lines, interface_fields=interface_fields, peers=peers)

    def render(self, server: Server, clients: list[Client], config_text: str) -> str:
        parsed = self.parse(config_text)
        existing_by_public_key = {peer.public_key: peer for peer in parsed.peers if peer.public_key}
        interface_private_key = parsed.interface_fields.get("PrivateKey", "").strip()
        clients_by_public_key = {
            client.public_key: client
            for client in clients
            if client.public_key
            and client.assigned_ip
            and not client.archived
            and client.status == "active"
            and not client.manual_disabled
            and not client.policy_disabled_reason
            and "/" in client.assigned_ip
            and client.public_key.strip() != interface_private_key
        }

        interface_block = "\n".join(parsed.interface_lines).strip()
        blocks: list[str] = [interface_block] if interface_block else ["[Interface]"]
        has_panel_clients = bool(clients_by_public_key)

        matched_public_keys: set[str] = set()
        ordered_clients: list[Client] = []
        for peer in parsed.peers:
            client = clients_by_public_key.get(peer.public_key)
            if client:
                ordered_clients.append(client)
        for client in clients:
            if client.public_key in clients_by_public_key and client.public_key not in {item.public_key for item in ordered_clients}:
                ordered_clients.append(client)

        for client in ordered_clients:
            if not client.public_key or client.public_key not in clients_by_public_key:
                continue
            existing = existing_by_public_key.get(client.public_key)
            if existing:
                matched_public_keys.add(client.public_key)

            peer_lines = ["[Peer]", self._client_comment(client), f"PublicKey = {client.public_key}"]
            preshared_key = existing.fields.get("PresharedKey") if existing else None
            if not preshared_key and client.preshared_key_encrypted:
                preshared_key = decrypt_value(client.preshared_key_encrypted)
            if preshared_key:
                peer_lines.append(f"PresharedKey = {preshared_key}")
            peer_lines.append(f"AllowedIPs = {client.assigned_ip}")

            persistent_keepalive = existing.fields.get("PersistentKeepalive") if existing else None
            if persistent_keepalive:
                peer_lines.append(f"PersistentKeepalive = {persistent_keepalive}")

            endpoint = existing.fields.get("Endpoint") if existing else None
            if endpoint:
                peer_lines.append(f"Endpoint = {endpoint}")

            for key in (existing.field_order if existing else []):
                if key in {"PublicKey", "PresharedKey", "AllowedIPs", "PersistentKeepalive", "Endpoint"}:
                    continue
                value = existing.fields.get(key)
                if value:
                    peer_lines.append(f"{key} = {value}")

            blocks.append("\n".join(peer_lines))

        for peer in parsed.peers:
            is_service_peer = any("service-exit-peer" in line for line in peer.raw_lines)
            if has_panel_clients and not is_service_peer:
                continue
            if not peer.public_key or peer.public_key in matched_public_keys:
                continue
            if is_service_peer:
                blocks.append("\n".join(peer.raw_lines).strip())
                continue
            peer_lines = ["[Peer]"]
            for key in peer.field_order:
                value = peer.fields.get(key)
                if value is not None:
                    peer_lines.append(f"{key} = {value}")
            if len(peer_lines) > 1:
                blocks.append("\n".join(peer_lines))

        return "\n\n".join(blocks).strip() + "\n"

    def render_with_service_peer(self, config_text: str, service_peer_block: str) -> str:
        parsed = self.parse(config_text)
        incoming = self.parse(service_peer_block)
        service_peer = incoming.peers[0] if incoming.peers else None
        if not service_peer or not service_peer.public_key:
            return config_text

        interface_block = "\n".join(parsed.interface_lines).strip()
        blocks: list[str] = [interface_block] if interface_block else ["[Interface]"]

        replaced = False
        for peer in parsed.peers:
            is_service_peer = any("service-exit-peer" in line for line in peer.raw_lines)
            if is_service_peer or peer.public_key == service_peer.public_key:
                if not replaced:
                    blocks.append("\n".join(service_peer.raw_lines).strip())
                    replaced = True
                continue
            blocks.append("\n".join(peer.raw_lines).strip())

        if not replaced:
            blocks.append("\n".join(service_peer.raw_lines).strip())

        return "\n\n".join(blocks).strip() + "\n"

    def remove_service_peer(self, config_text: str) -> str:
        parsed = self.parse(config_text)
        interface_block = "\n".join(parsed.interface_lines).strip()
        blocks: list[str] = [interface_block] if interface_block else ["[Interface]"]

        for peer in parsed.peers:
            is_service_peer = any("service-exit-peer" in line for line in peer.raw_lines)
            if is_service_peer:
                continue
            blocks.append("\n".join(peer.raw_lines).strip())

        return "\n\n".join(blocks).strip() + "\n"
