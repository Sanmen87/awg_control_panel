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
  apt-get install -y bash build-essential ca-certificates curl git golang-go iproute2 make pkg-config tar
fi
version_ge() {
  [ "$1" = "$2" ] && return 0
  [ "$(printf '%s\\n%s\\n' "$1" "$2" | sort -V | tail -n1)" = "$1" ]
}
map_go_arch() {
  case "$(uname -m)" in
    x86_64) echo amd64 ;;
    aarch64|arm64) echo arm64 ;;
    *) echo "" ;;
  esac
}
if ! command -v amneziawg-go >/dev/null 2>&1; then
  rm -rf /opt/amneziawg-go
  git clone https://github.com/amnezia-vpn/amneziawg-go /opt/amneziawg-go
  REQUIRED_GO_VERSION="$(awk '/^go / {print $2; exit}' /opt/amneziawg-go/go.mod)"
  CURRENT_GO_VERSION=""
  if command -v go >/dev/null 2>&1; then
    CURRENT_GO_VERSION="$(go version 2>/dev/null | awk '{print $3}' | sed 's/^go//')"
  fi
  if [ -z "$CURRENT_GO_VERSION" ] || [ -z "$REQUIRED_GO_VERSION" ] || ! version_ge "$CURRENT_GO_VERSION" "$REQUIRED_GO_VERSION"; then
    GO_ARCH="$(map_go_arch)"
    if [ -z "$GO_ARCH" ]; then
      echo "Unsupported architecture for automatic Go installation: $(uname -m)" >&2
      exit 1
    fi
    rm -rf /usr/local/go /tmp/go-toolchain.tar.gz
    curl -fsSL "https://go.dev/dl/go${REQUIRED_GO_VERSION}.linux-${GO_ARCH}.tar.gz" -o /tmp/go-toolchain.tar.gz
    tar -C /usr/local -xzf /tmp/go-toolchain.tar.gz
    rm -f /tmp/go-toolchain.tar.gz
    export PATH="/usr/local/go/bin:$PATH"
  fi
  make -C /opt/amneziawg-go
  install -m 0755 /opt/amneziawg-go/amneziawg-go /usr/local/bin/amneziawg-go
fi
if ! command -v awg >/dev/null 2>&1; then
  export PATH="/usr/local/go/bin:$PATH"
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
CUR_USER="$(whoami)"
mkdir -p /opt/amnezia/amnezia-awg /opt/amnezia/amnezia-dns /opt/amnezia/awg
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl iproute2 docker.io apparmor apparmor-utils
  systemctl enable docker || true
  systemctl restart docker || service docker restart || true
fi
chown "$CUR_USER" /opt/amnezia/amnezia-awg /opt/amnezia/amnezia-dns || true
if ! docker network ls | grep -q amnezia-dns-net; then
  docker network create \
    --driver bridge \
    --subnet=172.29.172.0/24 \
    --opt com.docker.network.bridge.name=amn0 \
    amnezia-dns-net
fi

rm -f /opt/amnezia/amnezia-awg/Dockerfile
cat > /opt/amnezia/amnezia-awg/Dockerfile <<'EOF'
FROM amneziavpn/amneziawg-go:latest
LABEL maintainer="AmneziaVPN"
RUN apk add --no-cache bash curl dumb-init
RUN apk --update upgrade --no-cache
RUN mkdir -p /opt/amnezia /opt/amnezia/awg
RUN echo -e "#!/bin/bash\ntail -f /dev/null" > /opt/amnezia/start.sh
RUN chmod a+x /opt/amnezia/start.sh
RUN echo -e " \n\
  fs.file-max = 51200 \n\
  \n\
  net.core.rmem_max = 67108864 \n\
  net.core.wmem_max = 67108864 \n\
  net.core.netdev_max_backlog = 250000 \n\
  net.core.somaxconn = 4096 \n\
  \n\
  net.ipv4.tcp_syncookies = 1 \n\
  net.ipv4.tcp_tw_reuse = 1 \n\
  net.ipv4.tcp_tw_recycle = 0 \n\
  net.ipv4.tcp_fin_timeout = 30 \n\
  net.ipv4.tcp_keepalive_time = 1200 \n\
  net.ipv4.ip_local_port_range = 10000 65000 \n\
  net.ipv4.tcp_max_syn_backlog = 8192 \n\
  net.ipv4.tcp_max_tw_buckets = 5000 \n\
  net.ipv4.tcp_fastopen = 3 \n\
  net.ipv4.tcp_mem = 25600 51200 102400 \n\
  net.ipv4.tcp_rmem = 4096 87380 67108864 \n\
  net.ipv4.tcp_wmem = 4096 65536 67108864 \n\
  net.ipv4.tcp_mtu_probing = 1 \n\
  net.ipv4.tcp_congestion_control = hybla \n\
  " | sed -e 's/^\s\+//g' | tee -a /etc/sysctl.conf && \
  mkdir -p /etc/security && \
  echo -e " \n\
  * soft nofile 51200 \n\
  * hard nofile 51200 \n\
  " | sed -e 's/^\s\+//g' | tee -a /etc/security/limits.conf
ENTRYPOINT [ "dumb-init", "/opt/amnezia/start.sh" ]
CMD [ "" ]
EOF

rm -f /opt/amnezia/amnezia-dns/Dockerfile
cat > /opt/amnezia/amnezia-dns/Dockerfile <<'EOF'
FROM mvance/unbound:latest
LABEL maintainer="AmneziaVPN"
RUN echo " \n\
domain-insecure: \"coin.\"\n\
domain-insecure: \"emc.\"\n\
domain-insecure: \"lib.\"\n\
domain-insecure: \"bazar.\"\n\
domain-insecure: \"enum.\"\n\
\n\
stub-zone:\n\
   name: coin.\n\
   stub-host: seed1.emercoin.com\n\
   stub-host: seed2.emercoin.com\n\
   stub-first: yes\n\
\n\
stub-zone:\n\
   name: emc.\n\
   stub-host: seed1.emercoin.com\n\
   stub-host: seed2.emercoin.com\n\
   stub-first: yes\n\
\n\
stub-zone:\n\
   name: lib.\n\
   stub-host: seed1.emercoin.com\n\
   stub-host: seed2.emercoin.com\n\
   stub-first: yes\n\
\n\
stub-zone:\n\
   name: bazar.\n\
   stub-host: seed1.emercoin.com\n\
   stub-host: seed2.emercoin.com\n\
   stub-first: yes\n\
\n\
stub-zone:\n\
   name: enum.\n\
   stub-host: seed1.emercoin.com\n\
   stub-host: seed2.emercoin.com\n\
   stub-first: yes\n\
\n\
forward-zone:\n\
   name: .\n\
   forward-tls-upstream: yes\n\
   forward-addr: 1.1.1.1@853\n\
   forward-addr: 1.0.0.1@853\n\
" | tee /opt/unbound/etc/unbound/forward-records.conf
EOF

docker rm -f amnezia-dns >/dev/null 2>&1 || true
docker rm -f amnezia-awg >/dev/null 2>&1 || true
docker rmi amnezia-dns >/dev/null 2>&1 || true
docker rmi amnezia-awg >/dev/null 2>&1 || true
docker build --no-cache --pull -t amnezia-dns /opt/amnezia/amnezia-dns
docker build --no-cache --pull -t amnezia-awg /opt/amnezia/amnezia-awg
docker run -d \
  --log-driver none \
  --restart always \
  --network amnezia-dns-net \
  --ip=172.29.172.254 \
  --name amnezia-dns \
  amnezia-dns
docker run -d \
  --name amnezia-awg \
  --log-driver none \
  --restart always \
  --privileged \
  --cap-add=NET_ADMIN \
  --cap-add=SYS_MODULE \
  -p 51820:51820/udp \
  -v /lib/modules:/lib/modules \
  --sysctl="net.ipv4.conf.all.src_valid_mark=1" \
  --sysctl="net.ipv4.ip_forward=1" \
  amnezia-awg
docker network connect amnezia-dns-net amnezia-awg >/dev/null 2>&1 || true
sysctl -w net.ipv4.ip_forward=1

iptables_has_chain() {
  iptables -nL "$1" >/dev/null 2>&1
}

iptables -C FORWARD -j DOCKER-USER 2>/dev/null || {
  if iptables_has_chain DOCKER-USER; then
    iptables -A FORWARD -j DOCKER-USER
  fi
}
iptables -C FORWARD -j DOCKER-ISOLATION-STAGE-1 2>/dev/null || {
  if iptables_has_chain DOCKER-ISOLATION-STAGE-1; then
    iptables -A FORWARD -j DOCKER-ISOLATION-STAGE-1
  fi
}
iptables -C FORWARD -o amn0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || iptables -A FORWARD -o amn0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
iptables -C FORWARD -i amn0 ! -o amn0 -j ACCEPT 2>/dev/null || iptables -A FORWARD -i amn0 ! -o amn0 -j ACCEPT
iptables -C FORWARD -i amn0 -o amn0 -j ACCEPT 2>/dev/null || iptables -A FORWARD -i amn0 -o amn0 -j ACCEPT
iptables -C FORWARD -o docker0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || iptables -A FORWARD -o docker0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
iptables -C FORWARD -o docker0 -j DOCKER 2>/dev/null || {
  if iptables_has_chain DOCKER; then
    iptables -A FORWARD -o docker0 -j DOCKER
  fi
}
iptables -C FORWARD -i docker0 ! -o docker0 -j ACCEPT 2>/dev/null || iptables -A FORWARD -i docker0 ! -o docker0 -j ACCEPT
iptables -C FORWARD -i docker0 -o docker0 -j ACCEPT 2>/dev/null || iptables -A FORWARD -i docker0 -o docker0 -j ACCEPT
echo 'docker bootstrap complete'
""".strip()


def wrap_with_optional_sudo(command: str, sudo_password: str | None) -> str:
    quoted_command = shlex.quote(command)
    if sudo_password:
        quoted_password = shlex.quote(f"{sudo_password}\n")
        return f"printf %s {quoted_password} | sudo -S bash -lc {quoted_command}"
    return f"bash -lc {quoted_command}"
