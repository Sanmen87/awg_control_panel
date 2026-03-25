from __future__ import annotations


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
) -> str:
    return (
        "[Interface]\n"
        f"# topology: {topology_name}\n"
        f"# role: {role}\n"
        f"Address = {local_address}\n"
        "ListenPort = 51820\n"
        f"PrivateKey = {private_key}\n\n"
        "[Peer]\n"
        f"# interface: {interface_name}\n"
        f"PublicKey = {peer_public_key}\n"
        f"Endpoint = {endpoint}\n"
        f"AllowedIPs = {allowed_ips}\n"
        "PersistentKeepalive = 25\n"
    )


def render_standard_server_config(
    *,
    topology_name: str,
    interface_name: str,
    address: str,
    private_key: str,
    listen_port: int = 51820,
) -> str:
    return (
        "[Interface]\n"
        f"# topology: {topology_name}\n"
        "# role: standard-vpn\n"
        f"Address = {address}\n"
        f"ListenPort = {listen_port}\n"
        f"PrivateKey = {private_key}\n"
    )
