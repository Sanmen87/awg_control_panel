import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.server import AccessStatus, Server, ServerStatus
from app.models.server_runtime_sample import ServerRuntimeSample
from app.services.server_credentials import ServerCredentialsService
from app.services.ssh import SSHService

COLLECT_SERVER_METRICS_COMMAND = r"""sh -lc '
set -eu
cpu_line_1="$(grep "^cpu " /proc/stat)"
sleep 1
cpu_line_2="$(grep "^cpu " /proc/stat)"
cpu_percent="$(awk -v a="$cpu_line_1" -v b="$cpu_line_2" '"'"'
BEGIN {
  split(a, x, " ");
  split(b, y, " ");
  idle1 = x[5] + x[6];
  idle2 = y[5] + y[6];
  total1 = 0;
  total2 = 0;
  for (i = 2; i <= 11; i++) {
    total1 += x[i];
    total2 += y[i];
  }
  diff_total = total2 - total1;
  diff_idle = idle2 - idle1;
  if (diff_total <= 0) {
    printf "0.00";
  } else {
    printf "%.2f", ((diff_total - diff_idle) / diff_total) * 100;
  }
}
'"'"')"
mem_total_kb="$(awk '"'"'/MemTotal:/ {print $2}'"'"' /proc/meminfo)"
mem_available_kb="$(awk '"'"'/MemAvailable:/ {print $2}'"'"' /proc/meminfo)"
mem_used_kb=$((mem_total_kb - mem_available_kb))
disk_total_bytes="$(df -B1 / | awk '"'"'NR==2 {print $2}'"'"')"
disk_used_bytes="$(df -B1 / | awk '"'"'NR==2 {print $3}'"'"')"
iface="$(awk '"'"'$2 == "00000000" {print $1; exit}'"'"' /proc/net/route)"
if [ -z "${iface:-}" ]; then
  iface="$(awk -F: '"'"'NR>2 {gsub(/ /, "", $1); if ($1 != "lo") {print $1; exit}}'"'"' /proc/net/dev)"
fi
net_rx_bytes_total="0"
net_tx_bytes_total="0"
if [ -n "${iface:-}" ]; then
  net_line="$(grep -E "^[[:space:]]*${iface}:" /proc/net/dev | head -n1 || true)"
  if [ -n "${net_line:-}" ]; then
    net_rx_bytes_total="$(printf "%s\n" "$net_line" | tr ":" " " | awk "{print \$2}")"
    net_tx_bytes_total="$(printf "%s\n" "$net_line" | tr ":" " " | awk "{print \$10}")"
  fi
fi
uptime_seconds="$(cut -d. -f1 /proc/uptime)"
load1="$(awk '"'"'{print $1}'"'"' /proc/loadavg)"
load5="$(awk '"'"'{print $2}'"'"' /proc/loadavg)"
load15="$(awk '"'"'{print $3}'"'"' /proc/loadavg)"
container_status=""
if command -v docker >/dev/null 2>&1; then
  container_status="$(docker inspect -f "{{.State.Status}}" amnezia-awg 2>/dev/null || true)"
fi
printf "cpu_percent=%s\n" "$cpu_percent"
printf "memory_total_bytes=%s\n" "$((mem_total_kb * 1024))"
printf "memory_used_bytes=%s\n" "$((mem_used_kb * 1024))"
printf "disk_total_bytes=%s\n" "$disk_total_bytes"
printf "disk_used_bytes=%s\n" "$disk_used_bytes"
printf "network_interface=%s\n" "${iface:-}"
printf "network_rx_bytes_total=%s\n" "$net_rx_bytes_total"
printf "network_tx_bytes_total=%s\n" "$net_tx_bytes_total"
printf "uptime_seconds=%s\n" "$uptime_seconds"
printf "load1=%s\n" "$load1"
printf "load5=%s\n" "$load5"
printf "load15=%s\n" "$load15"
printf "container_status=%s\n" "$container_status"
'"""


@dataclass
class ServerMetricsSnapshot:
    cpu_percent: float
    memory_total_bytes: int
    memory_used_bytes: int
    disk_total_bytes: int
    disk_used_bytes: int
    network_interface: str | None
    network_rx_bytes_total: int
    network_tx_bytes_total: int
    network_rx_rate_bps: float
    network_tx_rate_bps: float
    uptime_seconds: int
    load1: float
    load5: float
    load15: float
    container_status: str | None
    sampled_at: datetime

    def to_json(self) -> str:
        return json.dumps(
            {
                "cpu_percent": self.cpu_percent,
                "memory_total_bytes": self.memory_total_bytes,
                "memory_used_bytes": self.memory_used_bytes,
                "disk_total_bytes": self.disk_total_bytes,
                "disk_used_bytes": self.disk_used_bytes,
                "network_interface": self.network_interface,
                "network_rx_bytes_total": self.network_rx_bytes_total,
                "network_tx_bytes_total": self.network_tx_bytes_total,
                "network_rx_rate_bps": self.network_rx_rate_bps,
                "network_tx_rate_bps": self.network_tx_rate_bps,
                "uptime_seconds": self.uptime_seconds,
                "load1": self.load1,
                "load5": self.load5,
                "load15": self.load15,
                "container_status": self.container_status,
                "sampled_at": self.sampled_at.isoformat(),
            }
        )


class ServerMetricsService:
    def __init__(self) -> None:
        self.ssh = SSHService()
        self.creds = ServerCredentialsService()

    @staticmethod
    def _parse_output(raw: str) -> dict[str, str]:
        payload: dict[str, str] = {}
        for line in raw.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", maxsplit=1)
            payload[key.strip()] = value.strip()
        return payload

    @staticmethod
    def _safe_float(value: str | None) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _safe_int(value: str | None) -> int:
        try:
            return int(float(value or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _load_previous_metrics(server: Server) -> dict[str, object]:
        if not server.host_metrics_json:
            return {}
        try:
            return json.loads(server.host_metrics_json)
        except json.JSONDecodeError:
            return {}

    def _build_snapshot(self, server: Server, payload: dict[str, str]) -> ServerMetricsSnapshot:
        sampled_at = datetime.now(UTC)
        previous_metrics = self._load_previous_metrics(server)
        previous_sampled_at = server.host_metrics_refreshed_at
        previous_rx = self._safe_int(str(previous_metrics.get("network_rx_bytes_total") or 0))
        previous_tx = self._safe_int(str(previous_metrics.get("network_tx_bytes_total") or 0))
        current_rx = self._safe_int(payload.get("network_rx_bytes_total"))
        current_tx = self._safe_int(payload.get("network_tx_bytes_total"))
        rx_rate_bps = 0.0
        tx_rate_bps = 0.0
        if previous_sampled_at:
            elapsed = max((sampled_at - previous_sampled_at).total_seconds(), 1.0)
            rx_delta = max(current_rx - previous_rx, 0)
            tx_delta = max(current_tx - previous_tx, 0)
            rx_rate_bps = (rx_delta * 8) / elapsed
            tx_rate_bps = (tx_delta * 8) / elapsed
        return ServerMetricsSnapshot(
            cpu_percent=self._safe_float(payload.get("cpu_percent")),
            memory_total_bytes=self._safe_int(payload.get("memory_total_bytes")),
            memory_used_bytes=self._safe_int(payload.get("memory_used_bytes")),
            disk_total_bytes=self._safe_int(payload.get("disk_total_bytes")),
            disk_used_bytes=self._safe_int(payload.get("disk_used_bytes")),
            network_interface=payload.get("network_interface") or None,
            network_rx_bytes_total=current_rx,
            network_tx_bytes_total=current_tx,
            network_rx_rate_bps=rx_rate_bps,
            network_tx_rate_bps=tx_rate_bps,
            uptime_seconds=self._safe_int(payload.get("uptime_seconds")),
            load1=self._safe_float(payload.get("load1")),
            load5=self._safe_float(payload.get("load5")),
            load15=self._safe_float(payload.get("load15")),
            container_status=payload.get("container_status") or None,
            sampled_at=sampled_at,
        )

    def _build_snapshot_from_agent_payload(self, server: Server, payload: dict[str, object]) -> ServerMetricsSnapshot:
        normalized = {key: str(value) for key, value in payload.items() if value is not None}
        return self._build_snapshot(server, normalized)

    async def collect(self, server: Server) -> ServerMetricsSnapshot:
        result = await self.ssh.run_command(
            host=server.host,
            username=server.ssh_user,
            port=server.ssh_port,
            password=self.creds.get_ssh_password(server),
            private_key=self.creds.get_private_key(server),
            command=COLLECT_SERVER_METRICS_COMMAND,
        )
        if result.exit_status != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Server metrics collection failed")
        payload = self._parse_output(result.stdout)
        return self._build_snapshot(server, payload)

    async def sync_server(self, db: Session, server: Server) -> bool:
        if server.access_status != AccessStatus.OK:
            return False
        snapshot = await self.collect(server)
        return self._persist_snapshot(db, server, snapshot)

    def sync_server_from_agent_payload(self, db: Session, server: Server, payload: dict[str, object]) -> bool:
        if server.access_status != AccessStatus.OK:
            return False
        snapshot = self._build_snapshot_from_agent_payload(server, payload)
        return self._persist_snapshot(db, server, snapshot)

    def _persist_snapshot(self, db: Session, server: Server, snapshot: ServerMetricsSnapshot) -> bool:
        server.host_metrics_json = snapshot.to_json()
        server.host_metrics_refreshed_at = snapshot.sampled_at
        server.status = ServerStatus.HEALTHY
        server.last_error = None
        server_sample = ServerRuntimeSample(
            server_id=server.id,
            sampled_at=snapshot.sampled_at,
            cpu_percent=snapshot.cpu_percent,
            memory_used_bytes=snapshot.memory_used_bytes,
            memory_total_bytes=snapshot.memory_total_bytes,
            disk_used_bytes=snapshot.disk_used_bytes,
            disk_total_bytes=snapshot.disk_total_bytes,
            network_rx_bytes_total=snapshot.network_rx_bytes_total,
            network_tx_bytes_total=snapshot.network_tx_bytes_total,
            network_rx_rate_bps=snapshot.network_rx_rate_bps,
            network_tx_rate_bps=snapshot.network_tx_rate_bps,
            uptime_seconds=snapshot.uptime_seconds,
            load1=snapshot.load1,
            load5=snapshot.load5,
            load15=snapshot.load15,
        )
        db.add(server)
        db.add(server_sample)
        return True

    def mark_collection_error(self, db: Session, server: Server, exc: Exception) -> None:
        server.status = ServerStatus.DEGRADED
        server.last_error = str(exc)
        db.add(server)
