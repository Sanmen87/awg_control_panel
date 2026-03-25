from __future__ import annotations

import base64
import io
import ipaddress
import json
import math
import struct
import zlib
from dataclasses import dataclass

import qrcode
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import x25519

from app.core.security import decrypt_value, encrypt_value
from app.models.client import Client
from app.models.server import Server
from app.services.awg_profile import AWG_PROFILE_FIELD_ORDER, AWGProfileService


@dataclass
class GeneratedClientMaterials:
    private_key: str
    public_key: str
    preshared_key: str
    assigned_ip: str
    ubuntu_config: str
    amneziawg_config: str
    amneziavpn_config: str
    qr_png_base64: str
    qr_png_base64_list: list[str]


class ClientMaterialsService:
    def __init__(self) -> None:
        self.awg_profile = AWGProfileService()

    def build_for_server(self, server: Server, name: str, assigned_ip: str, existing_psk: str | None = None) -> GeneratedClientMaterials:
        private_key, public_key = self._generate_keypair()
        preshared_key = existing_psk or self._generate_psk()
        server_public_key = self._derive_public_key_from_server(server)
        endpoint = f"{server.host}:{server.live_listen_port or 51820}"
        dns_value = self._server_dns(server)
        obfuscation_fields = self._extract_obfuscation_fields(server)

        amneziawg_config = self._render_client_config(
            client_name=name,
            assigned_ip=assigned_ip,
            private_key=private_key,
            preshared_key=preshared_key,
            server_public_key=server_public_key,
            endpoint=endpoint,
            dns_value=dns_value,
            extra_interface_fields=obfuscation_fields,
        )
        ubuntu_config = amneziawg_config
        amneziavpn_payload = self._build_amneziavpn_payload(
            server=server,
            name=name,
            assigned_ip=assigned_ip,
            private_key=private_key,
            preshared_key=preshared_key,
            server_public_key=server_public_key,
            endpoint=endpoint,
            dns_value=dns_value,
            awg_config=amneziawg_config,
            obfuscation_fields=obfuscation_fields,
        )
        amneziavpn_config = self._render_amneziavpn_text(amneziavpn_payload)
        qr_png_base64_list = self._generate_qr_png_base64_list(amneziavpn_payload)
        qr_png_base64 = qr_png_base64_list[0]
        return GeneratedClientMaterials(
            private_key=private_key,
            public_key=public_key,
            preshared_key=preshared_key,
            assigned_ip=assigned_ip,
            ubuntu_config=ubuntu_config,
            amneziawg_config=amneziawg_config,
            amneziavpn_config=amneziavpn_config,
            qr_png_base64=qr_png_base64,
            qr_png_base64_list=qr_png_base64_list,
        )

    def next_available_ip(self, server: Server, existing_assigned_ips: list[str]) -> str:
        if not server.live_address_cidr:
            raise RuntimeError("Server subnet is unknown")
        interface = ipaddress.ip_interface(server.live_address_cidr)
        network = interface.network
        occupied = set()
        occupied.add(str(interface.ip))
        for item in existing_assigned_ips:
            try:
                occupied.add(str(ipaddress.ip_interface(item).ip))
            except ValueError:
                continue

        for host in network.hosts():
            host_str = str(host)
            if host_str not in occupied:
                return f"{host_str}/32"
        raise RuntimeError("No free client IP addresses left in subnet")

    def decrypt_materials(self, client: Client) -> dict[str, str | list[str] | None]:
        amneziawg_config = self._decrypt_optional(client.config_amneziawg_encrypted)
        amneziavpn_config = self._decrypt_optional(client.config_amneziavpn_encrypted)
        amneziawg_qr_png_base64_list = self._generate_qr_png_base64_list(amneziawg_config.encode("utf-8")) if amneziawg_config else []
        amneziavpn_qr_png_base64_list = self._decrypt_qr_list(client.qr_png_base64_encrypted)
        if not amneziavpn_qr_png_base64_list and amneziavpn_config:
            amneziavpn_payload = self._decode_vpn_uri_payload(amneziavpn_config)
            if amneziavpn_payload:
                amneziavpn_qr_png_base64_list = self._generate_qr_png_base64_list(amneziavpn_payload)
        return {
            "ubuntu_config": self._decrypt_optional(client.config_ubuntu_encrypted),
            "amneziawg_config": amneziawg_config,
            "amneziavpn_config": amneziavpn_config,
            "qr_png_base64": amneziavpn_qr_png_base64_list[0] if amneziavpn_qr_png_base64_list else None,
            "qr_png_base64_list": amneziavpn_qr_png_base64_list,
            "amneziawg_qr_png_base64": amneziawg_qr_png_base64_list[0] if amneziawg_qr_png_base64_list else None,
            "amneziawg_qr_png_base64_list": amneziawg_qr_png_base64_list,
            "amneziavpn_qr_png_base64": amneziavpn_qr_png_base64_list[0] if amneziavpn_qr_png_base64_list else None,
            "amneziavpn_qr_png_base64_list": amneziavpn_qr_png_base64_list,
        }

    def _generate_keypair(self) -> tuple[str, str]:
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

    def _generate_psk(self) -> str:
        return base64.b64encode(x25519.X25519PrivateKey.generate().private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )).decode("utf-8")

    def _derive_public_key_from_server(self, server: Server) -> str:
        if not server.live_runtime_details_json:
            raise RuntimeError("Server live config is unavailable")
        runtime_details = json.loads(server.live_runtime_details_json)
        config_preview = runtime_details.get("config_preview") or ""
        private_key = None
        for line in config_preview.splitlines():
            stripped = line.strip()
            if stripped.startswith("PrivateKey = "):
                private_key = stripped.split("=", 1)[1].strip()
                break
        if not private_key:
            raise RuntimeError("Server private key is not available in live config")

        private_bytes = base64.b64decode(private_key.encode("utf-8"))
        private = x25519.X25519PrivateKey.from_private_bytes(private_bytes)
        public_raw = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.b64encode(public_raw).decode("utf-8")

    def _server_dns(self, server: Server) -> str:
        install_method = getattr(getattr(server, "install_method", None), "value", None)
        if install_method in {"go", "native"}:
            return "1.1.1.1, 1.0.0.1"
        try:
            interface = ipaddress.ip_interface(server.live_address_cidr or "")
            return str(interface.ip)
        except ValueError:
            return server.host

    def _render_client_config(
        self,
        *,
        client_name: str,
        assigned_ip: str,
        private_key: str,
        preshared_key: str,
        server_public_key: str,
        endpoint: str,
        dns_value: str,
        extra_interface_fields: dict[str, str] | None = None,
    ) -> str:
        lines = [
            "[Interface]",
            f"# client: {client_name}",
            f"Address = {assigned_ip}",
            f"PrivateKey = {private_key}",
            f"DNS = {dns_value}",
        ]
        for key in AWG_PROFILE_FIELD_ORDER:
            value = (extra_interface_fields or {}).get(key)
            if value:
                lines.append(f"{key} = {value}")
        lines.extend(
            [
                "",
                "[Peer]",
                f"PublicKey = {server_public_key}",
                f"PresharedKey = {preshared_key}",
                f"Endpoint = {endpoint}",
                "AllowedIPs = 0.0.0.0/0, ::/0",
                "PersistentKeepalive = 25",
            ]
        )
        return "\n".join(lines) + "\n"

    def _extract_obfuscation_fields(self, server: Server) -> dict[str, str]:
        if not server.live_runtime_details_json:
            return self.awg_profile.for_generated_server(server)
        runtime_details = json.loads(server.live_runtime_details_json)
        config_preview = runtime_details.get("config_preview") or ""
        fields: dict[str, str] = {}
        for line in config_preview.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            candidate = stripped
            if candidate.startswith("#"):
                candidate = candidate[1:].strip()
            if "=" not in candidate:
                continue
            key, value = candidate.split("=", 1)
            normalized_key = key.strip()
            if normalized_key in AWG_PROFILE_FIELD_ORDER:
                fields[normalized_key] = value.strip()
        normalized = self.awg_profile.normalize(fields)
        if normalized:
            return normalized
        return self.awg_profile.for_generated_server(server)

    def _build_amneziavpn_payload(
        self,
        *,
        server: Server,
        name: str,
        assigned_ip: str,
        private_key: str,
        preshared_key: str,
        server_public_key: str,
        endpoint: str,
        dns_value: str,
        awg_config: str,
        obfuscation_fields: dict[str, str],
    ) -> bytes:
        container_name = "amnezia-awg"
        container_config: dict[str, object] = {
            "last_config": json.dumps(
                self._build_amneziavpn_last_config(
                    awg_config=awg_config,
                    endpoint=endpoint,
                    assigned_ip=assigned_ip,
                    private_key=private_key,
                    preshared_key=preshared_key,
                    server_public_key=server_public_key,
                    obfuscation_fields=obfuscation_fields,
                ),
                ensure_ascii=False,
            ),
            "isThirdPartyConfig": True,
            "port": server.live_listen_port or 51820,
            "transport_proto": "udp",
        }
        protocol_version = self._detect_awg_protocol_version(obfuscation_fields)
        if protocol_version:
            container_config["protocol_version"] = protocol_version

        config = {
            "containers": [
                {
                    "container": container_name,
                    "awg": container_config,
                }
            ],
            "defaultContainer": container_name,
            "description": name,
            "dns1": dns_value,
            "hostName": server.host,
        }
        json_bytes = json.dumps(config, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return struct.pack(">I", len(json_bytes)) + zlib.compress(json_bytes, level=8)

    def _build_amneziavpn_last_config(
        self,
        *,
        awg_config: str,
        endpoint: str,
        assigned_ip: str,
        private_key: str,
        preshared_key: str,
        server_public_key: str,
        obfuscation_fields: dict[str, str],
    ) -> dict[str, object]:
        host, _, port = endpoint.rpartition(":")
        config: dict[str, object] = {
            "config": awg_config,
            "hostName": host,
            "port": int(port) if port.isdigit() else 51820,
            "client_priv_key": private_key,
            "client_ip": assigned_ip,
            "psk_key": preshared_key,
            "server_pub_key": server_public_key,
            "mtu": "1376",
            "persistent_keep_alive": "25",
            "allowed_ips": ["0.0.0.0/0", "::/0"],
        }
        for key in AWG_PROFILE_FIELD_ORDER:
            value = obfuscation_fields.get(key)
            if value:
                config[key] = value
        return config

    def _detect_awg_protocol_version(self, obfuscation_fields: dict[str, str]) -> str | None:
        if obfuscation_fields.get("S3") and obfuscation_fields.get("S4"):
            return "2"
        if any(obfuscation_fields.get(key) for key in ["I1", "I2", "I3", "I4", "I5"]):
            return "1.5"
        return None

    def _render_amneziavpn_text(self, payload: bytes) -> str:
        encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        return f"vpn://{encoded}"

    def _decode_vpn_uri_payload(self, value: str) -> bytes | None:
        if not value.startswith("vpn://"):
            return None
        encoded = value.removeprefix("vpn://").strip()
        if not encoded:
            return None
        padding = "=" * (-len(encoded) % 4)
        try:
            return base64.urlsafe_b64decode(encoded + padding)
        except (ValueError, base64.binascii.Error):
            return None

    def _generate_qr_png_base64_list(self, payload: bytes) -> list[str]:
        chunk_size = 850
        chunks_count = max(1, math.ceil(len(payload) / chunk_size))
        qr_images: list[str] = []
        for chunk_id in range(chunks_count):
            chunk_data = payload[chunk_id * chunk_size:(chunk_id + 1) * chunk_size]
            framed = struct.pack(">hBBI", 1984, chunks_count, chunk_id, len(chunk_data)) + chunk_data
            qr_payload = base64.urlsafe_b64encode(framed).decode("ascii").rstrip("=")
            qr_images.append(self._generate_qr_png_base64(qr_payload))
        return qr_images

    def _generate_qr_png_base64(self, payload: str) -> str:
        image = qrcode.make(payload)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    def _decrypt_optional(self, value: str | None) -> str | None:
        if not value:
            return None
        return decrypt_value(value)

    def encrypt_material(self, value: str | None) -> str | None:
        if not value:
            return None
        return encrypt_value(value)

    def encrypt_qr_material(self, values: list[str]) -> str | None:
        if not values:
            return None
        return encrypt_value(json.dumps(values))

    def _decrypt_qr_list(self, value: str | None) -> list[str]:
        decrypted = self._decrypt_optional(value)
        if not decrypted:
            return []
        try:
            parsed = json.loads(decrypted)
        except json.JSONDecodeError:
            return [decrypted]
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, str) and item]
        if isinstance(parsed, str) and parsed:
            return [parsed]
        return []
