from __future__ import annotations

import json
from dataclasses import dataclass


DETECT_AWG_COMMAND = r"""
set -e
AMNEZIAWG_GO=$(command -v amneziawg-go || true)
AWG_BIN=$(command -v awg || true)
AWG_QUICK_BIN=$(command -v awg-quick || true)
IP_BIN=$(command -v ip || true)
DOCKER_BIN=$(command -v docker || true)
DOCKER_CONTAINER=""
OS_NAME=""
OS_VERSION=""
find_awg_container() {
  docker ps -q 2>/dev/null | while read -r cid; do
    [ -n "$cid" ] || continue
    name=$(docker inspect --format '{{.Name}}' "$cid" 2>/dev/null | sed 's#^/##' || true)
    image=$(docker inspect --format '{{.Config.Image}}' "$cid" 2>/dev/null || true)
    mounts=$(docker inspect --format '{{range .Mounts}}{{println .Destination}}{{end}}' "$cid" 2>/dev/null | tr '\n' ' ' || true)
    score=0

    if printf '%s %s' "$name" "$image" | grep -Ei '(awg|wireguard)' >/dev/null; then
      score=$((score + 8))
    fi
    if printf '%s %s' "$name" "$image" | grep -Ei '(dns)' >/dev/null; then
      score=$((score - 6))
    fi
    if printf '%s' "$mounts" | grep -Ei '(/opt/amnezia/awg|/etc/wireguard|/etc/amnezia)' >/dev/null; then
      score=$((score + 5))
    fi

    if docker exec "$name" sh -lc 'test -d /opt/amnezia/awg || test -f /opt/amnezia/awg/wg0.conf || test -f /opt/amnezia/awg/clientsTable' >/dev/null 2>&1; then
      score=$((score + 20))
    fi
    if docker exec "$name" sh -lc 'command -v awg >/dev/null 2>&1 || command -v wg >/dev/null 2>&1' >/dev/null 2>&1; then
      score=$((score + 10))
    fi

    printf '%s|%s|%s\n' "$score" "$name" "$image"
  done | sort -t'|' -k1,1nr | head -n1 | cut -d'|' -f2-3
}

if [ -f /etc/os-release ]; then
  . /etc/os-release
  OS_NAME="${NAME:-}"
  OS_VERSION="${VERSION_ID:-${VERSION:-}}"
fi
VERSION=""
INSTALL_TYPE="unknown"
RUNTIME_FLAVOR="unknown"
if [ -n "$AMNEZIAWG_GO" ]; then
  VERSION=$($AMNEZIAWG_GO --version 2>/dev/null | head -n1 || true)
  INSTALL_TYPE="go"
  RUNTIME_FLAVOR="go-userspace"
elif [ -n "$DOCKER_BIN" ]; then
  DOCKER_CONTAINER=$(find_awg_container)
  if [ -n "$DOCKER_CONTAINER" ]; then
    INSTALL_TYPE="docker"
    RUNTIME_FLAVOR="docker-amnezia"
  fi
fi
if [ "$INSTALL_TYPE" = "unknown" ] && [ -n "$AWG_BIN" -o -n "$AWG_QUICK_BIN" ]; then
  INSTALL_TYPE="custom"
  if [ -n "$AWG_BIN" ] && [ -z "$AMNEZIAWG_GO" ]; then
    RUNTIME_FLAVOR="kernel-patched"
  else
    RUNTIME_FLAVOR="unknown-custom"
  fi
fi
INTERFACES=""
if [ -n "$IP_BIN" ]; then
  INTERFACES=$($IP_BIN -o link show | awk -F': ' '{print $2}' | paste -sd ',' - || true)
fi
printf '{"amneziawg_go":"%s","awg":"%s","awg_quick":"%s","os_name":"%s","os_version":"%s","version":"%s","interfaces":"%s","install_type":"%s","runtime_flavor":"%s"}\n' \
  "$AMNEZIAWG_GO" "$AWG_BIN" "$AWG_QUICK_BIN" "$OS_NAME" "$OS_VERSION" "$VERSION" "$INTERFACES" "$INSTALL_TYPE" "$RUNTIME_FLAVOR"
""".strip()


@dataclass
class AWGDetectionResult:
    detected: bool
    version: str | None
    os_name: str | None
    os_version: str | None
    install_type: str
    runtime_flavor: str | None
    interfaces_json: str
    raw: dict[str, str]


def parse_detection_output(stdout: str) -> AWGDetectionResult:
    payload = json.loads(stdout.strip().splitlines()[-1])
    interfaces = [item for item in payload.get("interfaces", "").split(",") if item]
    install_type = payload.get("install_type") or "unknown"
    detected = install_type in {"go", "native", "docker", "custom"}
    return AWGDetectionResult(
        detected=detected,
        version=payload.get("version") or None,
        os_name=payload.get("os_name") or None,
        os_version=payload.get("os_version") or None,
        install_type=install_type,
        runtime_flavor=payload.get("runtime_flavor") or None,
        interfaces_json=json.dumps(interfaces),
        raw=payload,
    )
