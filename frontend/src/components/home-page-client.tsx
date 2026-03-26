"use client";

import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "./api";
import { ProtectedApp } from "./protected-app";
import { useAuth } from "./auth-context";
import { useLocale } from "./locale-context";

type ServerMetrics = {
  cpu_percent: number;
  memory_total_bytes: number;
  memory_used_bytes: number;
  disk_total_bytes: number;
  disk_used_bytes: number;
  network_interface: string | null;
  network_rx_rate_bps: number;
  network_tx_rate_bps: number;
  uptime_seconds: number;
  load1: number;
  load5: number;
  load15: number;
  container_status: string | null;
  sampled_at: string | null;
};

type Server = {
  id: number;
  name: string;
  status: string;
  awg_detected: boolean;
  install_method: string;
  runtime_flavor: string | null;
  metrics: ServerMetrics | null;
};

type TopPeer = {
  id: number;
  name: string;
  status: string;
  server_name: string | null;
  runtime_connected: boolean;
  total_30d_bytes: number;
  rx_30d_bytes: number;
  tx_30d_bytes: number;
};

type ClientsAccess = {
  total: number;
  active: number;
  online: number;
  imported: number;
  generated: number;
  manual_disabled: number;
  policy_disabled: number;
  expiring_3d: number;
  expiring_7d: number;
};

type DashboardStats = {
  api_status: string;
  servers: Server[];
  top_peers: TopPeer[];
  clients_access: ClientsAccess;
};

export function HomePageClient() {
  const { token, logout } = useAuth();
  const { locale } = useLocale();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [selectedServerId, setSelectedServerId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const copy = locale === "ru"
    ? {
        title: "Рабочая панель управления AWG-инфраструктурой.",
        refresh: "Обновить",
        overview: "Обзор системы",
        api: "Состояние API",
        apiHint: "Backend и авторизация",
        apiOffline: "Недоступно",
        serverTitle: "Сервер",
        serverHint: "Минутные показатели хоста",
        serverSelect: "Сервер",
        noServerMetrics: "Для сервера пока нет метрик.",
        cpu: "CPU",
        memory: "ОЗУ",
        disk: "Диск",
        network: "Сеть",
        uptime: "Uptime",
        load: "Load",
        container: "Контейнер",
        sampledAt: "Обновлено",
        install: "Установка",
        runtime: "Runtime",
        topPeers: "Топ peer-ов по трафику",
        topPeersHint: "Rolling 30 дней",
        noPeers: "Пока нет данных по peer-ам.",
        serversList: "Состояние серверов",
        serversListHint: "Живы ли узлы и их uptime",
        serverOnline: "в сети",
        serverOffline: "выключен",
        noServers: "Серверов пока нет.",
        clientsTitle: "Клиенты и доступ",
        active: "Активны",
        online: "Онлайн",
        imported: "Импорт.",
        generated: "Сгенер.",
        manualPaused: "Вручную",
        policyPaused: "По policy",
        expiring3d: "Истекают 3д",
        expiring7d: "Истекают 7д",
        total: "Всего",
        noData: "Данные еще не загружены."
      }
    : {
        title: "Operational dashboard for the AWG control plane.",
        refresh: "Refresh",
        overview: "System overview",
        api: "API status",
        apiHint: "Backend and auth",
        apiOffline: "Offline",
        serverTitle: "Server",
        serverHint: "Host metrics sampled every minute",
        serverSelect: "Server",
        noServerMetrics: "No server metrics yet.",
        cpu: "CPU",
        memory: "RAM",
        disk: "Disk",
        network: "Network",
        uptime: "Uptime",
        load: "Load",
        container: "Container",
        sampledAt: "Updated",
        install: "Install",
        runtime: "Runtime",
        topPeers: "Top peers by traffic",
        topPeersHint: "Rolling 30 days",
        noPeers: "No peer traffic data yet.",
        serversList: "Server state",
        serversListHint: "Live state and uptime",
        serverOnline: "online",
        serverOffline: "offline",
        noServers: "No servers yet.",
        clientsTitle: "Clients and access",
        active: "Active",
        online: "Online",
        imported: "Imported",
        generated: "Generated",
        manualPaused: "Manual",
        policyPaused: "Policy",
        expiring3d: "Expire 3d",
        expiring7d: "Expire 7d",
        total: "Total",
        noData: "Data has not been loaded yet."
      };

  const selectedServer = useMemo(
    () => stats?.servers.find((server) => server.id === selectedServerId) ?? stats?.servers[0] ?? null,
    [selectedServerId, stats]
  );

  async function loadDashboard() {
    if (!token) {
      return;
    }
    try {
      const nextStats = await apiRequest<DashboardStats>("/dashboard/summary", { token });
      setStats(nextStats);
      setSelectedServerId((current) => current ?? nextStats.servers[0]?.id ?? null);
      setError(null);
    } catch (nextError) {
      const message = nextError instanceof Error ? nextError.message : "Failed to load dashboard";
      setError(message);
      if (message.includes("401")) {
        logout();
      }
    }
  }

  useEffect(() => {
    void loadDashboard();
  }, [token]);

  useEffect(() => {
    if (!token) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void loadDashboard();
    }, 60000);
    return () => window.clearInterval(intervalId);
  }, [token]);

  function formatBytes(value: number): string {
    if (!value) {
      return "0 B";
    }
    const units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let size = value;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex += 1;
    }
    return `${size.toFixed(size >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
  }

  function formatBitsPerSecond(value: number): string {
    if (!value) {
      return "0 bit/s";
    }
    const units = ["bit/s", "Kbit/s", "Mbit/s", "Gbit/s"];
    let speed = value;
    let unitIndex = 0;
    while (speed >= 1000 && unitIndex < units.length - 1) {
      speed /= 1000;
      unitIndex += 1;
    }
    return `${speed.toFixed(speed >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
  }

  function formatPercent(used: number, total: number): string {
    if (!total) {
      return "0%";
    }
    return `${((used / total) * 100).toFixed(0)}%`;
  }

  function formatUptime(seconds: number): string {
    if (!seconds) {
      return "0m";
    }
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (days > 0) {
      return `${days}d ${hours}h`;
    }
    if (hours > 0) {
      return `${hours}h ${minutes}m`;
    }
    return `${minutes}m`;
  }

  function hasFreshMetrics(server: Server): boolean {
    const sampledAt = server.metrics?.sampled_at;
    if (!sampledAt) {
      return false;
    }
    const sampledMs = new Date(sampledAt).getTime();
    if (!Number.isFinite(sampledMs)) {
      return false;
    }
    return Date.now() - sampledMs <= 3 * 60 * 1000;
  }

  function isServerOnline(server: Server): boolean {
    return hasFreshMetrics(server) && Boolean(server.metrics?.uptime_seconds);
  }

  return (
    <ProtectedApp>
      <div className="page-header">
        <div>
          <span className="eyebrow">Dashboard</span>
          <h2>{copy.title}</h2>
        </div>
        <button type="button" className="secondary-button" onClick={() => void loadDashboard()}>
          {copy.refresh}
        </button>
      </div>

      {error ? <div className="error-box">{error}</div> : null}

      <section className="panel-card">
        <span className="eyebrow">{copy.overview}</span>
        {stats ? (
          <div className="dashboard-grid">
            <article className="card dashboard-card">
              <span className="eyebrow">{copy.api}</span>
              <div className="metric">{stats.api_status || copy.apiOffline}</div>
              <p>{copy.apiHint}</p>
            </article>

            <article className="card dashboard-card dashboard-card-wide">
              <div className="dashboard-card-head">
                <div>
                  <span className="eyebrow">{copy.serverTitle}</span>
                  <p>{copy.serverHint}</p>
                </div>
                <label className="field dashboard-select-field">
                  <span>{copy.serverSelect}</span>
                  <select
                    value={selectedServer?.id ?? ""}
                    onChange={(event) => setSelectedServerId(Number(event.target.value))}
                  >
                    {stats.servers.map((server) => (
                      <option key={server.id} value={server.id}>
                        {server.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {selectedServer?.metrics ? (
                <div className="dashboard-server-grid">
                  <div className="dashboard-kpi">
                    <span className="eyebrow">{copy.cpu}</span>
                    <strong>{selectedServer.metrics.cpu_percent.toFixed(0)}%</strong>
                  </div>
                  <div className="dashboard-kpi">
                    <span className="eyebrow">{copy.memory}</span>
                    <strong>{formatPercent(selectedServer.metrics.memory_used_bytes, selectedServer.metrics.memory_total_bytes)}</strong>
                    <small>{formatBytes(selectedServer.metrics.memory_used_bytes)} / {formatBytes(selectedServer.metrics.memory_total_bytes)}</small>
                  </div>
                  <div className="dashboard-kpi">
                    <span className="eyebrow">{copy.disk}</span>
                    <strong>{formatPercent(selectedServer.metrics.disk_used_bytes, selectedServer.metrics.disk_total_bytes)}</strong>
                    <small>{formatBytes(selectedServer.metrics.disk_used_bytes)} / {formatBytes(selectedServer.metrics.disk_total_bytes)}</small>
                  </div>
                  <div className="dashboard-kpi">
                    <span className="eyebrow">{copy.network}</span>
                    <strong>{formatBitsPerSecond(selectedServer.metrics.network_rx_rate_bps)} ↓</strong>
                    <small>{formatBitsPerSecond(selectedServer.metrics.network_tx_rate_bps)} ↑</small>
                  </div>
                  <div className="dashboard-kpi">
                    <span className="eyebrow">{copy.uptime}</span>
                    <strong>{formatUptime(selectedServer.metrics.uptime_seconds)}</strong>
                    <small>{copy.sampledAt}: {selectedServer.metrics.sampled_at ? new Date(selectedServer.metrics.sampled_at).toLocaleString() : "—"}</small>
                  </div>
                  <div className="dashboard-kpi">
                    <span className="eyebrow">{copy.load}</span>
                    <strong>{selectedServer.metrics.load1.toFixed(2)}</strong>
                    <small>{selectedServer.metrics.load5.toFixed(2)} / {selectedServer.metrics.load15.toFixed(2)}</small>
                  </div>
                  <div className="dashboard-kpi">
                    <span className="eyebrow">{copy.install}</span>
                    <strong>{selectedServer.install_method}</strong>
                    <small>{copy.runtime}: {selectedServer.runtime_flavor ?? "—"}</small>
                  </div>
                  <div className="dashboard-kpi">
                    <span className="eyebrow">{copy.container}</span>
                    <strong>{selectedServer.metrics.container_status ?? "—"}</strong>
                    <small>{selectedServer.awg_detected ? "AWG detected" : "AWG missing"}</small>
                  </div>
                </div>
              ) : (
                <div className="empty-state">{copy.noServerMetrics}</div>
              )}
            </article>

            <article className="card dashboard-card">
              <span className="eyebrow">{copy.clientsTitle}</span>
              <div className="dashboard-stats-list">
                <div><span>{copy.total}</span><strong>{stats.clients_access.total}</strong></div>
                <div><span>{copy.active}</span><strong>{stats.clients_access.active}</strong></div>
                <div><span>{copy.online}</span><strong>{stats.clients_access.online}</strong></div>
                <div><span>{copy.imported}</span><strong>{stats.clients_access.imported}</strong></div>
                <div><span>{copy.generated}</span><strong>{stats.clients_access.generated}</strong></div>
                <div><span>{copy.manualPaused}</span><strong>{stats.clients_access.manual_disabled}</strong></div>
                <div><span>{copy.policyPaused}</span><strong>{stats.clients_access.policy_disabled}</strong></div>
                <div><span>{copy.expiring3d}</span><strong>{stats.clients_access.expiring_3d}</strong></div>
                <div><span>{copy.expiring7d}</span><strong>{stats.clients_access.expiring_7d}</strong></div>
              </div>
            </article>

            <article className="card dashboard-card">
              <div className="dashboard-card-head">
                <div>
                  <span className="eyebrow">{copy.topPeers}</span>
                  <p>{copy.topPeersHint}</p>
                </div>
              </div>
              {stats.top_peers.length ? (
                <div className="dashboard-peers-list">
                  {stats.top_peers.map((peer) => (
                    <div key={peer.id} className="dashboard-peer-row">
                      <div>
                        <strong>{peer.name}</strong>
                        <small>{peer.server_name ?? "—"}</small>
                      </div>
                      <div>
                        <strong>{formatBytes(peer.total_30d_bytes)}</strong>
                        <small>{formatBytes(peer.rx_30d_bytes)} RX / {formatBytes(peer.tx_30d_bytes)} TX</small>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="empty-state">{copy.noPeers}</div>
              )}
            </article>

            <article className="card dashboard-card">
              <div className="dashboard-card-head">
                <div>
                  <span className="eyebrow">{copy.serversList}</span>
                  <p>{copy.serversListHint}</p>
                </div>
              </div>
              {stats.servers.length ? (
                <div className="dashboard-servers-list">
                  {stats.servers.map((server) => {
                    const online = isServerOnline(server);
                    return (
                      <div key={server.id} className="dashboard-server-row">
                        <div>
                          <strong>{server.name}</strong>
                          <small>{online ? copy.serverOnline : copy.serverOffline}</small>
                        </div>
                        <div>
                          <strong>{online && server.metrics ? formatUptime(server.metrics.uptime_seconds) : "—"}</strong>
                          <small>{server.install_method}</small>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="empty-state">{copy.noServers}</div>
              )}
            </article>
          </div>
        ) : (
          <div className="empty-state">{copy.noData}</div>
        )}
      </section>
    </ProtectedApp>
  );
}
