"use client";

import { FormEvent, useEffect, useState } from "react";

import { apiRequest } from "./api";
import { ProtectedApp } from "./protected-app";
import { useAuth } from "./auth-context";
import { useLocale } from "./locale-context";

type Server = {
  id: number;
  name: string;
  host: string;
  ssh_port: number;
  ssh_user: string;
  auth_method: string;
  install_method: string;
  runtime_flavor: string | null;
  status: string;
  access_status: string;
  awg_status: string;
  os_name: string | null;
  os_version: string | null;
  awg_detected: boolean;
  awg_version: string | null;
  config_source: string;
  live_interface_name: string | null;
  live_config_path: string | null;
  live_address_cidr: string | null;
  live_listen_port: number | null;
  live_peer_count: number | null;
  live_runtime_details_json: string | null;
  metadata_json: string | null;
  topology_name: string | null;
  ready_for_topology: boolean;
  ready_for_managed_clients: boolean;
  last_error: string | null;
};

type LiveRuntimeDetails = {
  runtime?: string;
  docker_container?: string;
  docker_image?: string;
  docker_mounts?: string;
  config_preview?: string;
  clients_table_preview?: string;
  peers?: Array<Record<string, string>>;
};

type ServerMetadata = {
  country_code?: string;
  country_name?: string;
  city?: string;
  resolved_ip?: string;
  network_scope?: string;
  geo_error?: string;
  failover_agent?: {
    status?: string;
    service?: string;
    active_exit_server_id?: number | null;
    moved_override_clients?: number | null;
    last_check_at?: string | null;
    last_switch_at?: string | null;
    last_switch_reason?: string | null;
    last_error?: string | null;
  };
  panel_agent?: {
    status?: string;
    version?: string | null;
    last_seen_at?: string | null;
    last_sync_at?: string | null;
    last_error?: string | null;
    sync_enabled?: boolean;
    pending_local_tasks?: number;
    pending_local_results?: number;
  };
};

type Job = {
  id: number;
  job_type: string;
  status: string;
  server_id: number | null;
  result_message: string | null;
  created_at: string;
  updated_at: string;
};

const initialForm = {
  name: "",
  host: "",
  ssh_port: 22,
  ssh_user: "root",
  auth_method: "password",
  ssh_password: "",
  ssh_private_key: "",
  sudo_password: ""
};

function hasServiceExitPeer(configPreview?: string | null) {
  return typeof configPreview === "string" && configPreview.includes("# service-exit-peer");
}

export function ServersPageClient() {
  const { token, logout } = useAuth();
  const { locale } = useLocale();
  const [servers, setServers] = useState<Server[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [form, setForm] = useState(initialForm);
  const [editNames, setEditNames] = useState<Record<number, string>>({});
  const [installMethodByServer, setInstallMethodByServer] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [workingServerId, setWorkingServerId] = useState<number | null>(null);
  const [deletingServerId, setDeletingServerId] = useState<number | null>(null);
  const [agentWorkingServerId, setAgentWorkingServerId] = useState<number | null>(null);
  const [agentActionInfo, setAgentActionInfo] = useState<Record<number, string>>({});

  const copy = locale === "ru"
    ? {
        title: "Подготовка сервера одним пайплайном: SSH, AWG, импорт текущего конфига и краткая инвентаризация.",
        refresh: "Обновить",
        newServer: "Новый сервер",
        serverList: "Список серверов",
        empty: "Серверы еще не добавлены.",
        add: "Добавить сервер",
        saving: "Сохранение...",
        created: "Сервер добавлен. Теперь нажмите «Подготовить сервер».",
        deleting: "Удаление...",
        preparing: "Подготовка...",
        prepare: "Подготовить сервер",
        install: "Установить AWG",
        installMethodCard: "Способ установки AWG",
        installHint: "SSH уже работает, но AWG не найден. Выберите способ установки и запустите bootstrap прямо из карточки сервера.",
        installRunning: "Идёт установка AWG...",
        installFinished: "Установка завершена",
        installFailed: "Установка завершилась с ошибкой",
        stageCheck: "Проверка SSH и диагностика",
        stageInstall: "Установка AWG",
        saveName: "Сохранить имя",
        remove: "Удалить",
        confirmRemove: "Удалить сервер? Если он используется в topology, операция будет запрещена.",
        ready: "Готов к topology",
        readyManaged: "Готов к клиентам",
        runtimeOnly: "Только runtime",
        notReady: "Не готов",
        imported: "Imported",
        generated: "Generated",
        noLiveConfig: "Live config отсутствует",
        importedLive: "Live config импортирован",
        generatedLive: "Generated config применён",
        helper:
          "После добавления сервер можно одним действием проверить, определить AWG и импортировать текущий конфиг. В карточке остаются только короткие итоговые статусы.",
        labels: {
          name: "Имя сервера",
          host: "IP / Host",
          sshPort: "SSH порт",
          sshUser: "SSH пользователь",
          auth: "Авторизация",
          password: "Пароль",
          privateKey: "SSH private key",
          sudoPassword: "Sudo пароль",
          ssh: "SSH",
          os: "ОС",
          awg: "AWG",
          runtime: "Runtime",
          failoverAgent: "Failover agent",
          panelAgent: "Панельный агент",
          activeExit: "Активный exit",
          backupPeers: "Peer-ов на backup",
          topology: "Topology",
          subnet: "Подсеть",
          port: "Порт",
          clients: "Клиентов",
          config: "Конфиг",
          diagnostics: "Диагностика",
          notAssigned: "не добавлен",
          agentSync: "Web sync",
          agentQueue: "Локальная очередь",
          agentResults: "Локальные результаты"
        }
        ,
        agentRefresh: "Проверить агента",
        agentSyncResults: "Забрать результаты",
        agentUnavailable: "не установлен",
        agentInstall: "Установить агент",
        agentReinstall: "Переустановить агент",
        agentInstalling: "Установка агента...",
        agentReinstalling: "Переустановка агента...",
        agentInstalledOk: "Агент установлен и конфиг обновлён.",
        agentReinstalledOk: "Агент переустановлен и конфиг обновлён.",
        agentRefreshOk: "Статус агента обновлён.",
        agentResultsOk: "Локальные результаты агента синхронизированы.",
      }
    : {
        title: "Prepare a server with one pipeline: SSH, AWG detection, live config import, and compact inventory.",
        refresh: "Refresh",
        newServer: "New server",
        serverList: "Server list",
        empty: "No servers added yet.",
        add: "Add server",
        saving: "Saving...",
        created: "Server added. Now click “Prepare server”.",
        deleting: "Deleting...",
        preparing: "Preparing...",
        prepare: "Prepare server",
        install: "Install AWG",
        installMethodCard: "AWG install method",
        installHint: "SSH is already working, but AWG is not detected. Choose the install method and start bootstrap directly from the server card.",
        installRunning: "AWG installation is in progress...",
        installFinished: "Installation completed",
        installFailed: "Installation failed",
        stageCheck: "SSH check and diagnostics",
        stageInstall: "AWG installation",
        saveName: "Save name",
        remove: "Delete",
        confirmRemove: "Delete this server? If it is attached to a topology, the operation will be blocked.",
        ready: "Ready for topology",
        readyManaged: "Ready for clients",
        runtimeOnly: "Runtime only",
        notReady: "Not ready",
        imported: "Imported",
        generated: "Generated",
        noLiveConfig: "Live config missing",
        importedLive: "Live config imported",
        generatedLive: "Generated config deployed",
        helper:
          "After adding a server, one action can verify SSH, detect AWG, and import the current config. The card keeps only short resulting statuses.",
        labels: {
          name: "Server name",
          host: "IP / Host",
          sshPort: "SSH port",
          sshUser: "SSH user",
          auth: "Authentication",
          password: "Password",
          privateKey: "SSH private key",
          sudoPassword: "Sudo password",
          ssh: "SSH",
          os: "OS",
          awg: "AWG",
          runtime: "Runtime",
          failoverAgent: "Failover agent",
          panelAgent: "Panel agent",
          activeExit: "Active exit",
          backupPeers: "Peers on backup",
          topology: "Topology",
          subnet: "Subnet",
          port: "Port",
          clients: "Clients",
          config: "Config",
          diagnostics: "Diagnostics",
          notAssigned: "not assigned",
          agentSync: "Web sync",
          agentQueue: "Local queue",
          agentResults: "Local results"
        }
        ,
        agentRefresh: "Refresh agent",
        agentSyncResults: "Fetch results",
        agentUnavailable: "not installed",
        agentInstall: "Install agent",
        agentReinstall: "Reinstall agent",
        agentInstalling: "Installing agent...",
        agentReinstalling: "Reinstalling agent...",
        agentInstalledOk: "Agent installed and config refreshed.",
        agentReinstalledOk: "Agent reinstalled and config refreshed.",
        agentRefreshOk: "Agent status refreshed.",
        agentResultsOk: "Local agent results synchronized.",
      };

  async function loadServers() {
    if (!token) {
      return;
    }
    try {
      const nextServers = await apiRequest<Server[]>("/servers", { token });
      setServers(nextServers);
      setEditNames(
        nextServers.reduce<Record<number, string>>((acc, server) => {
          acc[server.id] = server.name;
          return acc;
        }, {})
      );
      setInstallMethodByServer((current) =>
        nextServers.reduce<Record<number, string>>((acc, server) => {
          acc[server.id] =
            current[server.id]
            ?? (server.install_method === "go" || server.install_method === "native" ? "go" : "docker");
          return acc;
        }, {})
      );
      setError(null);
    } catch (nextError) {
      const message = nextError instanceof Error ? nextError.message : "Failed to load servers";
      setError(message);
      if (message.includes("401")) {
        logout();
      }
    }
  }

  useEffect(() => {
    void loadServers();
  }, [token]);

  useEffect(() => {
    if (!token) {
      return;
    }

    let cancelled = false;

    async function loadJobs() {
      try {
        const nextJobs = await apiRequest<Job[]>("/jobs", { token });
        if (!cancelled) {
          setJobs(nextJobs);
        }
        await loadServers();
      } catch {
        // keep last known jobs state
      }
    }

    void loadJobs();
    const timer = window.setInterval(() => {
      void loadJobs();
    }, 4000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [token]);

  function parseRuntimeDetails(server: Server): LiveRuntimeDetails | null {
    if (!server.live_runtime_details_json) {
      return null;
    }
    try {
      return JSON.parse(server.live_runtime_details_json) as LiveRuntimeDetails;
    } catch {
      return null;
    }
  }

  function parseServerMetadata(raw: string | null): ServerMetadata | null {
    if (!raw) {
      return null;
    }
    try {
      return JSON.parse(raw) as ServerMetadata;
    } catch {
      return null;
    }
  }

  function parseMetadata(server: Server): ServerMetadata | null {
    return parseServerMetadata(server.metadata_json);
  }

  function flagForCountry(countryCode?: string) {
    if (!countryCode) {
      return null;
    }
    if (countryCode === "LAN") {
      return "🖧";
    }
    if (!/^[A-Z]{2}$/.test(countryCode)) {
      return null;
    }
    return String.fromCodePoint(...Array.from(countryCode).map((char) => 127397 + char.charCodeAt(0)));
  }

  function geoTitle(metadata: ServerMetadata | null) {
    if (!metadata?.country_code) {
      return null;
    }
    if (metadata.country_code === "LAN") {
      return locale === "ru" ? "Локальная сеть" : "Local network";
    }
    if (metadata.country_name && metadata.city) {
      return `${metadata.country_name}, ${metadata.city}`;
    }
    return metadata.country_name ?? null;
  }

  function isDebugMessage(value: string | null) {
    return Boolean(value && value.startsWith("DEBUG "));
  }

  function summaryAwg(server: Server, details: LiveRuntimeDetails | null) {
    if (!server.awg_detected) {
      return server.awg_status;
    }
    if (server.install_method === "docker" && details?.docker_container) {
      return `docker (${details.docker_container})`;
    }
    if (server.install_method === "go" || server.install_method === "native") {
      return "go";
    }
    return server.runtime_flavor ?? server.install_method;
  }

  function configStage(server: Server) {
    if (!server.awg_detected) {
      return copy.notReady;
    }
    if (!server.ready_for_managed_clients) {
      return copy.runtimeOnly;
    }
    return server.config_source === "imported" ? copy.importedLive : copy.generatedLive;
  }

  function failoverAgentSummary(server: Server) {
    const metadata = parseMetadata(server);
    const agent = metadata?.failover_agent;
    if (!agent) {
      return "-";
    }
    if (agent.service === "running" || agent.status === "running") {
      return "running";
    }
    if (agent.service === "error" || agent.status === "error") {
      return "error";
    }
    return agent.service || agent.status || "unknown";
  }

  function failoverActiveExit(server: Server) {
    const metadata = parseMetadata(server);
    const exitId = metadata?.failover_agent?.active_exit_server_id;
    if (!exitId) {
      return null;
    }
    return servers.find((item) => item.id === exitId)?.name ?? `#${exitId}`;
  }

  function failoverReasonLabel(server: Server) {
    const metadata = parseMetadata(server);
    const reason = metadata?.failover_agent?.last_switch_reason;
    if (!reason) {
      return null;
    }
    if (reason === "active-exit-healthcheck-failed") {
      return locale === "ru" ? "Переключение из-за недоступности текущего exit" : "Switched because the current exit became unavailable";
    }
    if (reason === "auto-failback-to-primary") {
      return locale === "ru" ? "Автовозврат на основной exit" : "Automatic return to the primary exit";
    }
    return reason;
  }

  function panelAgentSummary(server: Server) {
    const agent = parseMetadata(server)?.panel_agent;
    if (!agent) {
      return copy.agentUnavailable;
    }
    return agent.status || "unknown";
  }

  function shouldShowInstallAgent(server: Server) {
    const agent = parseMetadata(server)?.panel_agent;
    return !agent || agent.status === "enrolled";
  }

  async function installAgent(serverId: number) {
    if (!token) {
      return;
    }
    const targetServer = servers.find((item) => item.id === serverId);
    const isReinstall = targetServer ? !shouldShowInstallAgent(targetServer) : false;
    setAgentWorkingServerId(serverId);
    setAgentActionInfo((current) => ({
      ...current,
      [serverId]: isReinstall ? copy.agentReinstalling : copy.agentInstalling
    }));
    try {
      await apiRequest(`/agents/install/${serverId}`, {
        method: "POST",
        token
      });
      await loadServers();
      setAgentActionInfo((current) => ({
        ...current,
        [serverId]: isReinstall ? copy.agentReinstalledOk : copy.agentInstalledOk
      }));
    } catch (nextError) {
      const message = nextError instanceof Error ? nextError.message : "Failed to install agent";
      setAgentActionInfo((current) => ({
        ...current,
        [serverId]: message
      }));
      setError(nextError instanceof Error ? nextError.message : "Failed to install agent");
    } finally {
      setAgentWorkingServerId(null);
    }
  }

  async function refreshAgentStatus(serverId: number) {
    if (!token) {
      return;
    }
    setAgentWorkingServerId(serverId);
    setAgentActionInfo((current) => ({
      ...current,
      [serverId]: copy.agentRefresh
    }));
    try {
      await apiRequest(`/agents/${serverId}/local-status`, {
        method: "GET",
        token
      });
      await loadServers();
      setAgentActionInfo((current) => ({
        ...current,
        [serverId]: copy.agentRefreshOk
      }));
    } catch (nextError) {
      const message = nextError instanceof Error ? nextError.message : "Failed to refresh agent";
      setAgentActionInfo((current) => ({
        ...current,
        [serverId]: message
      }));
      setError(nextError instanceof Error ? nextError.message : "Failed to refresh agent");
    } finally {
      setAgentWorkingServerId(null);
    }
  }

  async function syncAgentResults(serverId: number) {
    if (!token) {
      return;
    }
    setAgentWorkingServerId(serverId);
    setAgentActionInfo((current) => ({
      ...current,
      [serverId]: copy.agentSyncResults
    }));
    try {
      await apiRequest(`/agents/${serverId}/sync-local-results`, {
        method: "POST",
        token
      });
      await loadServers();
      setAgentActionInfo((current) => ({
        ...current,
        [serverId]: copy.agentResultsOk
      }));
    } catch (nextError) {
      const message = nextError instanceof Error ? nextError.message : "Failed to sync agent results";
      setAgentActionInfo((current) => ({
        ...current,
        [serverId]: message
      }));
      setError(nextError instanceof Error ? nextError.message : "Failed to sync agent results");
    } finally {
      setAgentWorkingServerId(null);
    }
  }

  function latestServerJob(serverId: number, jobType?: string) {
    return jobs.find((job) => job.server_id === serverId && (!jobType || job.job_type === jobType)) ?? null;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }
    setLoading(true);
    try {
      await apiRequest<Server>("/servers", {
        method: "POST",
        token,
        body: {
          name: form.name || null,
          host: form.host,
          ssh_port: Number(form.ssh_port) || 22,
          ssh_user: form.ssh_user,
          auth_method: form.auth_method,
          ssh_password: form.auth_method === "password" ? form.ssh_password || null : null,
          ssh_private_key: form.auth_method === "key" ? form.ssh_private_key || null : null,
          sudo_password: form.sudo_password || null
        }
      });
      setInfo(copy.created);
      setForm(initialForm);
      await loadServers();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to create server");
    } finally {
      setLoading(false);
    }
  }

  async function prepareServer(serverId: number) {
    if (!token) {
      return;
    }
    setWorkingServerId(serverId);
    try {
      await apiRequest<Server>(`/servers/${serverId}/prepare`, {
        method: "POST",
        token
      });
      setInfo(null);
      await loadServers();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to prepare server");
    } finally {
      setWorkingServerId(null);
    }
  }

  async function bootstrapServer(serverId: number) {
    if (!token) {
      return;
    }
    setWorkingServerId(serverId);
    try {
      await apiRequest(`/servers/${serverId}/bootstrap`, {
        method: "POST",
        token,
        body: {
          install_method: installMethodByServer[serverId] === "go" ? "go" : "docker"
        }
      });
      await loadServers();
      const nextJobs = await apiRequest<Job[]>("/jobs", { token });
      setJobs(nextJobs);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to bootstrap server");
    } finally {
      setWorkingServerId(null);
    }
  }

  async function saveServerName(serverId: number) {
    if (!token) {
      return;
    }
    setWorkingServerId(serverId);
    try {
      await apiRequest<Server>(`/servers/${serverId}`, {
        method: "PATCH",
        token,
        body: {
          name: editNames[serverId]
        }
      });
      await loadServers();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to update server");
    } finally {
      setWorkingServerId(null);
    }
  }

  async function deleteServer(serverId: number) {
    if (!token) {
      return;
    }
    if (!window.confirm(copy.confirmRemove)) {
      return;
    }
    setDeletingServerId(serverId);
    try {
      await apiRequest<void>(`/servers/${serverId}`, {
        method: "DELETE",
        token
      });
      setInfo(null);
      await loadServers();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to delete server");
    } finally {
      setDeletingServerId(null);
    }
  }

  return (
    <ProtectedApp>
      <div className="page-header page-header-with-fixed-action">
        <div>
          <span className="eyebrow">Servers</span>
          <h2>{copy.title}</h2>
        </div>
        <button
          type="button"
          className="secondary-button page-action-fixed"
          onClick={() => void loadServers()}
        >
          {copy.refresh}
        </button>
      </div>

      {error ? <div className="error-box">{error}</div> : null}
      {info ? <div className="info-box">{info}</div> : null}

      <section className="content-grid">
        <form className="panel-card" onSubmit={handleSubmit}>
          <span className="eyebrow">{copy.newServer}</span>
          <p>{copy.helper}</p>
          <div className="form-grid">
            <label className="field">
              <span>{copy.labels.name}</span>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label className="field">
              <span>{copy.labels.host}</span>
              <input value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} required />
            </label>
            <label className="field">
              <span>{copy.labels.sshPort}</span>
              <input
                type="number"
                value={form.ssh_port}
                onChange={(e) => setForm({ ...form, ssh_port: Number(e.target.value) })}
              />
            </label>
            <label className="field">
              <span>{copy.labels.sshUser}</span>
              <input value={form.ssh_user} onChange={(e) => setForm({ ...form, ssh_user: e.target.value })} />
            </label>
            <label className="field">
              <span>{copy.labels.auth}</span>
              <select
                value={form.auth_method}
                onChange={(e) => setForm({ ...form, auth_method: e.target.value, ssh_password: "", ssh_private_key: "" })}
              >
                <option value="password">password</option>
                <option value="key">key</option>
              </select>
            </label>
            {form.auth_method === "password" ? (
              <label className="field field-wide">
                <span>{copy.labels.password}</span>
                <input
                  type="password"
                  value={form.ssh_password}
                  onChange={(e) => setForm({ ...form, ssh_password: e.target.value })}
                />
              </label>
            ) : (
              <label className="field field-wide">
                <span>{copy.labels.privateKey}</span>
                <textarea
                  className="textarea-input"
                  value={form.ssh_private_key}
                  onChange={(e) => setForm({ ...form, ssh_private_key: e.target.value })}
                />
              </label>
            )}
            <label className="field field-wide">
              <span>{copy.labels.sudoPassword}</span>
              <input
                type="password"
                value={form.sudo_password}
                onChange={(e) => setForm({ ...form, sudo_password: e.target.value })}
              />
            </label>
          </div>
          <button type="submit" className="primary-button" disabled={loading}>
            {loading ? copy.saving : copy.add}
          </button>
        </form>

        <div className="panel-card">
          <span className="eyebrow">{copy.serverList}</span>
          <div className="server-list">
            {servers.length === 0 ? (
              <div className="empty-state">{copy.empty}</div>
            ) : (
              servers.map((server) => {
                const details = parseRuntimeDetails(server);
                const metadata = parseMetadata(server);
                const bootstrapJob = latestServerJob(server.id, "bootstrap-server");
                const flag = flagForCountry(metadata?.country_code);
                const flagTitle = geoTitle(metadata);
                const clientCount = server.live_peer_count ?? details?.peers?.length ?? 0;
                const servicePeerPresent = hasServiceExitPeer(details?.config_preview);
                const needsInstall = server.access_status === "ok" && !server.awg_detected;
                return (
                  <article key={server.id} className="server-card">
                    <div className="server-card-header">
                      <div>
                        <h3 className="server-name-row">
                          {flag ? (
                            <span className="country-flag" title={flagTitle ?? undefined}>
                              {flag}
                            </span>
                          ) : null}
                          <span>{server.name}</span>
                        </h3>
                        <p>{server.host}:{server.ssh_port} as {server.ssh_user}</p>
                      </div>
                      <div className="action-row compact-action-row">
                        <span className={server.ready_for_topology ? "status-badge status-succeeded" : "status-badge status-pending"}>
                          {server.ready_for_topology ? copy.ready : copy.notReady}
                        </span>
                        <span className={server.ready_for_managed_clients ? "status-badge status-succeeded" : "status-badge status-pending"}>
                          {server.ready_for_managed_clients ? copy.readyManaged : copy.runtimeOnly}
                        </span>
                        <span className="status-badge">{summaryAwg(server, details)}</span>
                        <span className="status-badge">
                          {configStage(server)}
                        </span>
                      </div>
                    </div>

                    <div className="form-grid compact-form-grid">
                      <label className="field">
                        <span>{copy.labels.name}</span>
                        <input
                          value={editNames[server.id] ?? server.name}
                          onChange={(event) => setEditNames({ ...editNames, [server.id]: event.target.value })}
                        />
                      </label>
                      <div className="field field-action">
                        <span>&nbsp;</span>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => void saveServerName(server.id)}
                          disabled={workingServerId === server.id}
                        >
                          {copy.saveName}
                        </button>
                      </div>
                    </div>

                    <div className="server-meta">
                      <span>{copy.labels.ssh}: {server.access_status}</span>
                      <span>{copy.labels.os}: {server.os_name ?? "-"} {server.os_version ?? ""}</span>
                      <span>{copy.labels.awg}: {summaryAwg(server, details)}</span>
                      <span>{copy.labels.runtime}: {details?.docker_container ?? details?.runtime ?? "-"}</span>
                      <span>{copy.labels.failoverAgent}: {failoverAgentSummary(server)}</span>
                      <span>{copy.labels.panelAgent}: {panelAgentSummary(server)}</span>
                      {failoverActiveExit(server) ? <span>{copy.labels.activeExit}: {failoverActiveExit(server)}</span> : null}
                      <span>{copy.labels.topology}: {server.topology_name ?? copy.labels.notAssigned}</span>
                      <span>{copy.labels.subnet}: {server.live_address_cidr ?? "-"}</span>
                      <span>{copy.labels.port}: {server.live_listen_port ?? "-"}</span>
                      <span>{copy.labels.clients}: {clientCount}</span>
                    </div>

                    {metadata?.failover_agent ? (
                      <div className="server-failover-card">
                        <div className="server-failover-head">
                          <strong>{copy.labels.failoverAgent}</strong>
                          <span className={`status-badge ${
                            failoverAgentSummary(server) === "running"
                              ? "status-succeeded"
                              : failoverAgentSummary(server) === "error"
                                ? "status-failed"
                                : "status-pending"
                          }`}>
                            {failoverAgentSummary(server)}
                          </span>
                        </div>
                        <div className="server-meta">
                          {failoverActiveExit(server) ? <span>{copy.labels.activeExit}: {failoverActiveExit(server)}</span> : null}
                          {typeof metadata.failover_agent.moved_override_clients === "number" ? (
                            <span>{copy.labels.backupPeers}: {metadata.failover_agent.moved_override_clients}</span>
                          ) : null}
                          {metadata.failover_agent.last_switch_at ? <span>last_switch: {metadata.failover_agent.last_switch_at}</span> : null}
                        </div>
                        {failoverReasonLabel(server) ? (
                          <div className="info-box">{failoverReasonLabel(server)}</div>
                        ) : null}
                      </div>
                    ) : null}

                    {metadata?.panel_agent ? (
                      <div className="server-failover-card">
                        <div className="server-failover-head">
                          <strong>{copy.labels.panelAgent}</strong>
                          <span className={`status-badge ${
                            metadata.panel_agent.status === "running" || metadata.panel_agent.status === "online"
                              ? "status-succeeded"
                              : metadata.panel_agent.status === "offline" || metadata.panel_agent.status === "error"
                                ? "status-failed"
                                : "status-pending"
                          }`}>
                            {panelAgentSummary(server)}
                          </span>
                        </div>
                        <div className="server-meta">
                          <span>{copy.labels.agentSync}: {metadata.panel_agent.sync_enabled ? "enabled" : "local-only"}</span>
                          <span>{copy.labels.agentQueue}: {metadata.panel_agent.pending_local_tasks ?? 0}</span>
                          <span>{copy.labels.agentResults}: {metadata.panel_agent.pending_local_results ?? 0}</span>
                          {metadata.panel_agent.version ? <span>version: {metadata.panel_agent.version}</span> : null}
                          {metadata.panel_agent.last_seen_at ? <span>last_seen: {metadata.panel_agent.last_seen_at}</span> : null}
                          {metadata.panel_agent.last_sync_at ? <span>last_sync: {metadata.panel_agent.last_sync_at}</span> : null}
                        </div>
                        {metadata.panel_agent.last_error ? <div className="info-box">{metadata.panel_agent.last_error}</div> : null}
                        {agentActionInfo[server.id] ? <div className="info-box">{agentActionInfo[server.id]}</div> : null}
                        <div className="action-row compact-action-row">
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={() => void installAgent(server.id)}
                            disabled={agentWorkingServerId === server.id}
                          >
                            {copy.agentReinstall}
                          </button>
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={() => void refreshAgentStatus(server.id)}
                            disabled={agentWorkingServerId === server.id}
                          >
                            {copy.agentRefresh}
                          </button>
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={() => void syncAgentResults(server.id)}
                            disabled={agentWorkingServerId === server.id}
                          >
                            {copy.agentSyncResults}
                          </button>
                        </div>
                      </div>
                    ) : null}

                    {!isDebugMessage(server.last_error) && server.last_error ? (
                      <div className="error-box">{server.last_error}</div>
                    ) : null}

                    <div className="action-row">
                      {!metadata?.panel_agent && agentActionInfo[server.id] ? (
                        <div className="info-box">{agentActionInfo[server.id]}</div>
                      ) : null}
                      {shouldShowInstallAgent(server) ? (
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => void installAgent(server.id)}
                          disabled={agentWorkingServerId === server.id}
                        >
                          {copy.agentInstall}
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="primary-button"
                        onClick={() => void prepareServer(server.id)}
                        disabled={workingServerId === server.id}
                      >
                        {workingServerId === server.id ? copy.preparing : copy.prepare}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => void deleteServer(server.id)}
                        disabled={deletingServerId === server.id}
                      >
                        {deletingServerId === server.id ? copy.deleting : copy.remove}
                      </button>
                    </div>

                    {needsInstall ? (
                      <div className="info-box">
                        <div className="server-install-grid">
                          <div>
                            <strong>{copy.installMethodCard}</strong>
                            <p>{copy.installHint}</p>
                          </div>
                          <label className="field">
                            <span>{copy.installMethodCard}</span>
                            <select
                              value={installMethodByServer[server.id] ?? "docker"}
                              onChange={(event) => setInstallMethodByServer({ ...installMethodByServer, [server.id]: event.target.value })}
                            >
                              <option value="docker">docker</option>
                              <option value="go">go</option>
                            </select>
                          </label>
                          <div className="field field-action">
                            <span>&nbsp;</span>
                            <button
                              type="button"
                              className="primary-button"
                              disabled={workingServerId === server.id}
                              onClick={() => void bootstrapServer(server.id)}
                            >
                              {workingServerId === server.id ? copy.installRunning : copy.install}
                            </button>
                          </div>
                        </div>

                        {bootstrapJob ? (
                          <div className="server-bootstrap-status">
                            <span className={`status-badge ${
                              bootstrapJob.status === "succeeded"
                                ? "status-succeeded"
                                : bootstrapJob.status === "failed"
                                  ? "status-failed"
                                  : "status-pending"
                            }`}>
                              {bootstrapJob.status === "running" || bootstrapJob.status === "pending"
                                ? copy.installRunning
                                : bootstrapJob.status === "succeeded"
                                  ? copy.installFinished
                                  : copy.installFailed}
                            </span>
                            {bootstrapJob.result_message ? <pre className="log-box">{bootstrapJob.result_message}</pre> : null}
                          </div>
                        ) : (
                          <div className="server-bootstrap-status">
                            <span className="status-badge status-pending">{copy.stageCheck}</span>
                          </div>
                        )}
                      </div>
                    ) : null}

                    {details?.config_preview ? (
                      <details className="preview-item server-details-block">
                        <summary>{copy.labels.config}</summary>
                        <pre className="log-box">{details.config_preview}</pre>
                      </details>
                    ) : null}

                    {servicePeerPresent ? (
                      <div className="info-box">service-peer: topology link present in live config</div>
                    ) : null}

                    <details className="preview-item server-details-block">
                      <summary>{copy.labels.diagnostics}</summary>
                      <div className="server-meta">
                        {server.live_config_path ? <span>config: {server.live_config_path}</span> : null}
                        {details?.docker_image ? <span>image: {details.docker_image}</span> : null}
                        {details?.docker_mounts ? <span>mounts: {details.docker_mounts}</span> : null}
                        {metadata?.failover_agent?.last_check_at ? <span>failover_last_check: {metadata.failover_agent.last_check_at}</span> : null}
                        {metadata?.failover_agent?.last_switch_at ? <span>failover_last_switch: {metadata.failover_agent.last_switch_at}</span> : null}
                        {metadata?.failover_agent?.last_switch_reason ? <span>failover_reason: {metadata.failover_agent.last_switch_reason}</span> : null}
                        {metadata?.failover_agent?.last_error ? <span>failover_error: {metadata.failover_agent.last_error}</span> : null}
                        {metadata?.resolved_ip ? <span>resolved_ip: {metadata.resolved_ip}</span> : null}
                        {metadata?.country_code ? <span>country: {metadata.country_code}</span> : null}
                        {metadata?.geo_error ? <span>geo_error: {metadata.geo_error}</span> : null}
                      </div>
                      {details?.clients_table_preview ? (
                        <pre className="log-box">{details.clients_table_preview}</pre>
                      ) : null}
                      {server.last_error ? <div className="info-box">{server.last_error}</div> : null}
                    </details>
                  </article>
                );
              })
            )}
          </div>
        </div>
      </section>
    </ProtectedApp>
  );
}
