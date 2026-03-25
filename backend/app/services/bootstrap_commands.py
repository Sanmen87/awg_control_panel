import shlex

CHECK_SERVER_COMMAND = r"""
set -e
OS_NAME=""
OS_VERSION=""
if [ -f /etc/os-release ]; then
  . /etc/os-release
  OS_NAME="${NAME:-}"
  OS_VERSION="${VERSION_ID:-${VERSION:-}}"
fi
printf '{"ssh":"ok","os_name":"%s","os_version":"%s","hostname":"%s"}\n' "$OS_NAME" "$OS_VERSION" "$(hostname)"
""".strip()

BOOTSTRAP_SERVER_GO_COMMAND = """
set -e
mkdir -p /opt/awg-control-panel
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y bash build-essential ca-certificates curl git golang-go iproute2 make pkg-config
fi
if ! command -v amneziawg-go >/dev/null 2>&1; then
  rm -rf /opt/amneziawg-go
  git clone https://github.com/amnezia-vpn/amneziawg-go /opt/amneziawg-go
  make -C /opt/amneziawg-go
  install -m 0755 /opt/amneziawg-go/amneziawg-go /usr/local/bin/amneziawg-go
fi
if ! command -v awg >/dev/null 2>&1; then
  rm -rf /opt/amneziawg-tools
  git clone https://github.com/amnezia-vpn/amneziawg-tools /opt/amneziawg-tools
  make -C /opt/amneziawg-tools/src
  make -C /opt/amneziawg-tools/src install WITH_WGQUICK=yes WITH_SYSTEMDUNITS=yes
fi
mkdir -p /etc/amnezia/amneziawg
sysctl -w net.ipv4.ip_forward=1
echo 'go bootstrap complete'
""".strip()

BOOTSTRAP_SERVER_DOCKER_COMMAND = r"""
set -e
mkdir -p /opt/awg-control-panel/docker-awg /opt/amnezia/awg
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl git iproute2 docker.io
  systemctl enable docker || true
  systemctl restart docker || service docker restart || true
fi

cat > /opt/awg-control-panel/docker-awg/Dockerfile <<'EOF'
FROM debian:12-slim
RUN apt-get update && apt-get install -y \
    bash ca-certificates curl git golang-go make gcc libc6-dev iproute2 iptables kmod procps \
    && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/amnezia-vpn/amneziawg-go /opt/amneziawg-go \
    && make -C /opt/amneziawg-go \
    && install -m 0755 /opt/amneziawg-go/amneziawg-go /usr/local/bin/amneziawg-go
RUN git clone https://github.com/amnezia-vpn/amneziawg-tools /opt/amneziawg-tools \
    && make -C /opt/amneziawg-tools/src \
    && make -C /opt/amneziawg-tools/src install WITH_WGQUICK=yes WITH_SYSTEMDUNITS=no
RUN mkdir -p /opt/amnezia/awg
CMD ["bash", "-lc", "mkdir -p /opt/amnezia/awg && tail -f /dev/null"]
EOF

docker build -t awg-control-panel/amnezia-awg-local /opt/awg-control-panel/docker-awg
docker rm -f amnezia-awg >/dev/null 2>&1 || true
docker run -d \
  --name amnezia-awg \
  --restart unless-stopped \
  --cap-add NET_ADMIN \
  --cap-add SYS_MODULE \
  --device /dev/net/tun \
  --network host \
  -v /opt/amnezia/awg:/opt/amnezia/awg \
  awg-control-panel/amnezia-awg-local
sysctl -w net.ipv4.ip_forward=1
echo 'docker bootstrap complete'
""".strip()


def wrap_with_optional_sudo(command: str, sudo_password: str | None) -> str:
    quoted_command = shlex.quote(command)
    if sudo_password:
        quoted_password = shlex.quote(f"{sudo_password}\n")
        return f"printf %s {quoted_password} | sudo -S bash -lc {quoted_command}"
    return f"bash -lc {quoted_command}"
