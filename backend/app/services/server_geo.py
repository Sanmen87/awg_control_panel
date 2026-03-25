import ipaddress
import json
import socket
from dataclasses import dataclass
from pathlib import Path

try:
    import IP2Location
except ImportError:  # pragma: no cover - depends on container image rebuild
    IP2Location = None


@dataclass
class ServerGeoResult:
    resolved_ip: str | None = None
    country_code: str | None = None
    country_name: str | None = None
    city: str | None = None
    is_private: bool = False
    error: str | None = None


class ServerGeoService:
    DB_PATH = Path("/app/geo/IP2LOCATION-LITE-DB3.BIN")
    _db = None

    def lookup(self, host: str) -> ServerGeoResult:
        resolved_ip = self._resolve_ip(host)
        if not resolved_ip:
            return ServerGeoResult(error="resolve_failed")

        try:
            ip_obj = ipaddress.ip_address(resolved_ip)
        except ValueError:
            return ServerGeoResult(resolved_ip=resolved_ip, error="invalid_ip")

        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            return ServerGeoResult(
                resolved_ip=resolved_ip,
                country_code="LAN",
                country_name="Local network",
                is_private=True,
            )

        if IP2Location is None:
            return ServerGeoResult(resolved_ip=resolved_ip, error="ip2location_module_missing")
        if not self.DB_PATH.exists():
            return ServerGeoResult(resolved_ip=resolved_ip, error="ip2location_db_missing")

        try:
            record = self._get_db().get_all(resolved_ip)
        except Exception as exc:  # noqa: BLE001
            return ServerGeoResult(resolved_ip=resolved_ip, error=f"ip2location_lookup_failed:{exc}")

        country_code = self._clean(record.country_short)
        country_name = self._clean(record.country_long)
        city = self._clean(record.city)
        if not country_code:
            return ServerGeoResult(resolved_ip=resolved_ip, error="ip2location_no_country")

        return ServerGeoResult(
            resolved_ip=resolved_ip,
            country_code=country_code.upper(),
            country_name=country_name,
            city=city,
            is_private=False,
        )

    def update_metadata_json(self, current_metadata_json: str | None, host: str) -> str | None:
        metadata = self._load_metadata(current_metadata_json)
        result = self.lookup(host)

        if result.resolved_ip:
            metadata["resolved_ip"] = result.resolved_ip
        if result.country_code:
            metadata["country_code"] = result.country_code
        if result.country_name:
            metadata["country_name"] = result.country_name
        if result.city:
            metadata["city"] = result.city
        if result.is_private:
            metadata["network_scope"] = "private"
        elif result.country_code:
            metadata["network_scope"] = "public"

        if result.error:
            metadata["geo_error"] = result.error
        else:
            metadata.pop("geo_error", None)

        return json.dumps(metadata) if metadata else None

    def _load_metadata(self, current_metadata_json: str | None) -> dict[str, str]:
        if not current_metadata_json:
            return {}
        try:
            parsed = json.loads(current_metadata_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _resolve_ip(self, host: str) -> str | None:
        if not host:
            return None

        candidate = host.strip()
        if not candidate:
            return None

        try:
            ipaddress.ip_address(candidate)
            return candidate
        except ValueError:
            pass

        try:
            infos = socket.getaddrinfo(candidate, None, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            return None

        for family, _, _, _, sockaddr in infos:
            if family == socket.AF_INET:
                return sockaddr[0]
        for family, _, _, _, sockaddr in infos:
            if family == socket.AF_INET6:
                return sockaddr[0]
        return None

    def _get_db(self):
        if self.__class__._db is None:
            database = IP2Location.IP2Location()
            database.open(str(self.DB_PATH))
            self.__class__._db = database
        return self.__class__._db

    def _clean(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        if not cleaned or cleaned == "-" or cleaned.upper() == "NOT SUPPORTED":
            return None
        return cleaned
