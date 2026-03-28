from __future__ import annotations

from app.services.awg_profile import AWG_PROFILE_FIELD_ORDER


def render_link_config(
    *,
    topology_name: str,
    role: str,
    interface_name: str,
    local_address: str,
    private_key: str,
    peer_public_key: str,
    endpoint: str,
    allowed_ips: str,
    extra_interface_fields: dict[str, str] | None = None,
) -> str:
    lines = [
        "[Interface]",
        f"# topology: {topology_name}",
        f"# role: {role}",
        f"Address = {local_address}",
        "ListenPort = 51820",
        f"PrivateKey = {private_key}",
    ]
    for key in AWG_PROFILE_FIELD_ORDER:
        value = (extra_interface_fields or {}).get(key)
        if value and str(value).strip() not in {"0", "0.0"}:
            lines.append(f"{key} = {value}")
    lines.extend(
        [
            "",
            "[Peer]",
            f"# interface: {interface_name}",
            f"PublicKey = {peer_public_key}",
            f"Endpoint = {endpoint}",
            f"AllowedIPs = {allowed_ips}",
            "PersistentKeepalive = 25",
        ]
    )
    return "\n".join(lines) + "\n"


def render_standard_server_config(
    *,
    topology_name: str,
    interface_name: str,
    address: str,
    private_key: str,
    listen_port: int = 51820,
    extra_interface_fields: dict[str, str] | None = None,
) -> str:
    lines = [
        "[Interface]",
        f"# topology: {topology_name}",
        "# role: standard-vpn",
        f"Address = {address}",
        f"ListenPort = {listen_port}",
        f"PrivateKey = {private_key}",
    ]
    for key in AWG_PROFILE_FIELD_ORDER:
        value = (extra_interface_fields or {}).get(key)
        if value and str(value).strip() not in {"0", "0.0"}:
            lines.append(f"{key} = {value}")
    return "\n".join(lines) + "\n"
