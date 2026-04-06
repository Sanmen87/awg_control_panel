"use client";

import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "./api";
import { ProtectedApp } from "./protected-app";
import { useAuth } from "./auth-context";
import { useLocale } from "./locale-context";

type EligibleServer = {
  id: number;
  name: string;
  host: string;
  topology_name: string | null;
  topology_role: string | null;
};

type ExtraService = {
  id: number;
  service_type: string;
  server_id: number;
  server_name: string | null;
  server_host: string | null;
  topology_name: string | null;
  topology_role: string | null;
  status: string;
  config_json: string | null;
  runtime_details_json: string | null;
  public_endpoint: string | null;
  last_error: string | null;
  install_job_id: number | null;
  install_job_status: string | null;
  install_job_task_id: string | null;
  install_job_updated_at: string | null;
  created_at: string;
  updated_at: string;
};

type MtProxyConfig = {
  repo_url?: string;
  port?: number;
  stats_port?: number;
  domain?: string;
  secret?: string;
  tg_url?: string;
  install_state?: string;
  image_mode?: string;
};

type Socks5Config = {
  repo_url?: string;
  port?: number;
  username?: string;
  password?: string;
  install_state?: string;
  image_mode?: string;
};

type XrayConfig = {
  repo_url?: string;
  port?: number;
  server_name?: string;
  uuid?: string;
  public_key?: string;
  short_id?: string;
  client_uri?: string;
  install_state?: string;
  image_mode?: string;
};

export function ExtraServicesPageClient() {
  const { token } = useAuth();
  const { locale } = useLocale();
  const [servers, setServers] = useState<EligibleServer[]>([]);
  const [services, setServices] = useState<ExtraService[]>([]);
  const [selectedServerId, setSelectedServerId] = useState("");
  const [selectedSocksServerId, setSelectedSocksServerId] = useState("");
  const [selectedXrayServerId, setSelectedXrayServerId] = useState("");
  const [domainInput, setDomainInput] = useState("vk.com");
  const [xrayDomainInput, setXrayDomainInput] = useState("www.apple.com");
  const [loading, setLoading] = useState<"mtproxy" | "socks5" | "xray" | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [refreshingId, setRefreshingId] = useState<number | null>(null);
  const [deliveryServiceId, setDeliveryServiceId] = useState<number | null>(null);
  const [deliveryEmailInput, setDeliveryEmailInput] = useState("");
  const [sendingEmailServiceId, setSendingEmailServiceId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const normalizedDomain = domainInput.trim().toLowerCase();
  const domainTooLong = normalizedDomain.length > 0 && new TextEncoder().encode(normalizedDomain).length > 15;

  const copy = locale === "ru"
    ? {
        eyebrow: "Доп сервисы",
        title: "Дополнительные сервисы ставятся отдельно от VPN topology и не должны вмешиваться в AWG routing.",
        serviceTitle: "MTProxy",
        socksTitle: "SOCKS5",
        xrayTitle: "Xray / VLESS + Reality",
        repoLabel: "Официальный GitHub",
        socksRepoLabel: "Docker image",
        server: "Сервер",
        selectServer: "Выберите сервер",
        add: "Добавить MTProxy",
        adding: "Добавляю MTProxy...",
        addSocks: "Добавить SOCKS5",
        addingSocks: "Добавляю SOCKS5...",
        addXray: "Добавить Xray",
        addingXray: "Добавляю Xray...",
        domain: "Домен Fake TLS",
        domainHint: "Реальный публичный домен для TLS-маскировки. Сейчас используется script-mode с official docker image. Нужен короткий домен до 15 байт, например vk.com или ya.ru.",
        mtproxyProfile: "Профиль подключения",
        mtproxyAccessHint: "Эту ссылку можно импортировать прямо в Telegram как MTProxy.",
        copyLink: "Копировать",
        copyLinkAria: "Скопировать ссылку",
        copySuccess: "Ссылка скопирована в буфер.",
        copyFailed: "Не удалось скопировать ссылку.",
        installStarted: "Установка MTProxy запущена. Статус появится после обновления данных.",
        socksInstallStarted: "Установка SOCKS5 запущена. Статус появится после обновления данных.",
        xrayInstallStarted: "Установка Xray запущена. Статус появится после обновления данных.",
        alreadyOnServer: "На выбранном сервере MTProxy уже есть в панели.",
        socksAlreadyOnServer: "На выбранном сервере SOCKS5 уже есть в панели.",
        xrayAlreadyOnServer: "На выбранном сервере Xray уже есть в панели.",
        installed: "Установленные сервисы",
        empty: "Сервисов пока нет.",
        allowedHint: "Сейчас доступны только exit-ноды proxy-topology и standalone standard-серверы.",
        topology: "Topology",
        role: "Роль",
        status: "Статус",
        endpoint: "Endpoint",
        repo: "Репозиторий",
        stage: "Стадия",
        domainValue: "Fake TLS домен",
        modeValue: "Режим",
        username: "Логин",
        password: "Пароль",
        xrayServerName: "Reality server name",
        uuid: "UUID",
        publicKey: "Public key",
        shortId: "Short ID",
        xrayUri: "VLESS URI",
        xrayProfile: "Профиль подключения",
        xrayAccessHint: "Эту ссылку можно импортировать прямо в клиент с поддержкой VLESS + Reality.",
        installJob: "Задача установки",
        task: "Task",
        updated: "Обновлено",
        refresh: "Проверить статус",
        refreshing: "Проверяю...",
        remove: "Удалить",
        removing: "Удаляю...",
        deliverTitle: "Отправка доступа",
        deliverOpen: "Отправить по почте",
        deliverEmail: "Email",
        deliverSend: "Отправить",
        deliverSending: "Отправляю...",
        deliverHint: "На почту уйдёт MTProxy-ссылка и короткая инструкция подключения.",
        plannedHint: "MTProxy ставится на выбранный сервер отдельным контейнером и не должен вмешиваться в AWG routing.",
        socksHint: "SOCKS5 ставится на выбранный сервер отдельным контейнером с логином и паролем.",
        xrayHint: "Xray ставится как VLESS + Reality и выдаёт готовую ссылку для iPhone-клиентов с поддержкой Reality.",
        tgLink: "Telegram link",
      }
    : {
        eyebrow: "Extra services",
        title: "Additional services are kept separate from VPN topology and should not interfere with AWG routing.",
        serviceTitle: "MTProxy",
        socksTitle: "SOCKS5",
        xrayTitle: "Xray / VLESS + Reality",
        repoLabel: "Official GitHub",
        socksRepoLabel: "Docker image",
        server: "Server",
        selectServer: "Select server",
        add: "Add MTProxy",
        adding: "Adding MTProxy...",
        addSocks: "Add SOCKS5",
        addingSocks: "Adding SOCKS5...",
        addXray: "Add Xray",
        addingXray: "Adding Xray...",
        domain: "Fake TLS domain",
        domainHint: "A real public domain used for TLS camouflage. Script-mode with the official docker image needs a short domain up to 15 bytes, for example vk.com or ya.ru.",
        mtproxyProfile: "Connection profile",
        mtproxyAccessHint: "You can import this link directly into Telegram as an MTProxy.",
        copyLink: "Copy",
        copyLinkAria: "Copy link",
        copySuccess: "Link copied to clipboard.",
        copyFailed: "Failed to copy the link.",
        installStarted: "MTProxy installation started. Status will appear after the next refresh.",
        socksInstallStarted: "SOCKS5 installation started. Status will appear after the next refresh.",
        xrayInstallStarted: "Xray installation started. Status will appear after the next refresh.",
        alreadyOnServer: "MTProxy is already registered on the selected server.",
        socksAlreadyOnServer: "SOCKS5 is already registered on the selected server.",
        xrayAlreadyOnServer: "Xray is already registered on the selected server.",
        installed: "Installed services",
        empty: "No services yet.",
        allowedHint: "Only proxy-topology exit nodes and standalone standard servers are currently allowed.",
        topology: "Topology",
        role: "Role",
        status: "Status",
        endpoint: "Endpoint",
        repo: "Repository",
        stage: "Stage",
        domainValue: "Fake TLS domain",
        modeValue: "Mode",
        username: "Username",
        password: "Password",
        xrayServerName: "Reality server name",
        uuid: "UUID",
        publicKey: "Public key",
        shortId: "Short ID",
        xrayUri: "VLESS URI",
        xrayProfile: "Connection profile",
        xrayAccessHint: "You can import this link directly into a client which supports VLESS + Reality.",
        installJob: "Install job",
        task: "Task",
        updated: "Updated",
        refresh: "Refresh status",
        refreshing: "Refreshing...",
        remove: "Delete",
        removing: "Deleting...",
        deliverTitle: "Access delivery",
        deliverOpen: "Send by email",
        deliverEmail: "Email",
        deliverSend: "Send",
        deliverSending: "Sending...",
        deliverHint: "The email will include the MTProxy link and a short connection guide.",
        plannedHint: "MTProxy is installed on the selected server as a separate container and should not interfere with AWG routing.",
        socksHint: "SOCKS5 is installed on the selected server as a separate authenticated container.",
        xrayHint: "Xray is installed as VLESS + Reality and returns a ready-to-import link for iPhone clients with Reality support.",
        tgLink: "Telegram link",
      };

  async function loadData() {
    if (!token) {
      return;
    }
    try {
      const [nextServers, nextServices] = await Promise.all([
        apiRequest<EligibleServer[]>("/extra-services/eligible-servers", { token }),
        apiRequest<ExtraService[]>("/extra-services", { token }),
      ]);
      setServers(nextServers);
      setServices(nextServices);
      setError(null);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to load extra services");
    }
  }

  useEffect(() => {
    void loadData();
    if (!token) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void loadData();
    }, 10000);
    return () => window.clearInterval(intervalId);
  }, [token]);

  useEffect(() => {
    if (!selectedServerId && servers.length > 0) {
      setSelectedServerId(String(servers[0].id));
    }
  }, [servers, selectedServerId]);

  useEffect(() => {
    if (!selectedSocksServerId && servers.length > 0) {
      setSelectedSocksServerId(String(servers[0].id));
    }
  }, [servers, selectedSocksServerId]);

  useEffect(() => {
    if (!selectedXrayServerId && servers.length > 0) {
      setSelectedXrayServerId(String(servers[0].id));
    }
  }, [servers, selectedXrayServerId]);

  const mtProxyServices = useMemo(
    () => services.filter((item) => item.service_type === "mtproxy"),
    [services]
  );
  const socks5Services = useMemo(
    () => services.filter((item) => item.service_type === "socks5"),
    [services]
  );
  const xrayServices = useMemo(
    () => services.filter((item) => item.service_type === "xray"),
    [services]
  );
  const selectedServerHasMtProxy = useMemo(
    () => mtProxyServices.some((item) => String(item.server_id) === selectedServerId),
    [mtProxyServices, selectedServerId]
  );
  const selectedServerHasSocks5 = useMemo(
    () => socks5Services.some((item) => String(item.server_id) === selectedSocksServerId),
    [socks5Services, selectedSocksServerId]
  );
  const selectedServerHasXray = useMemo(
    () => xrayServices.some((item) => String(item.server_id) === selectedXrayServerId),
    [xrayServices, selectedXrayServerId]
  );

  async function handleCreateMtProxy() {
    if (!token || !selectedServerId || loading || selectedServerHasMtProxy || !domainInput.trim() || domainTooLong) {
      return;
    }
    setLoading("mtproxy");
    setError(null);
    setInfo(null);
    try {
      await apiRequest<ExtraService>("/extra-services", {
        method: "POST",
        token,
        body: {
          service_type: "mtproxy",
          server_id: Number(selectedServerId),
          domain: domainInput.trim(),
        },
      });
      setInfo(copy.installStarted);
      await loadData();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to add MTProxy");
    } finally {
      setLoading(null);
    }
  }

  async function handleCreateSocks5() {
    if (!token || !selectedSocksServerId || loading || selectedServerHasSocks5) {
      return;
    }
    setLoading("xray");
    setError(null);
    setInfo(null);
    try {
      await apiRequest<ExtraService>("/extra-services", {
        method: "POST",
        token,
        body: {
          service_type: "socks5",
          server_id: Number(selectedSocksServerId),
        },
      });
      setInfo(copy.socksInstallStarted);
      await loadData();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to add SOCKS5");
    } finally {
      setLoading(null);
    }
  }

  async function handleCreateXray() {
    if (!token || !selectedXrayServerId || loading || !xrayDomainInput.trim() || selectedServerHasXray) {
      return;
    }
    setLoading("socks5");
    setError(null);
    setInfo(null);
    try {
      await apiRequest<ExtraService>("/extra-services", {
        method: "POST",
        token,
        body: {
          service_type: "xray",
          server_id: Number(selectedXrayServerId),
          domain: xrayDomainInput.trim(),
        },
      });
      setInfo(copy.xrayInstallStarted);
      await loadData();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to add Xray");
    } finally {
      setLoading(null);
    }
  }

  async function handleDelete(serviceId: number) {
    if (!token) {
      return;
    }
    setDeletingId(serviceId);
    setError(null);
    setInfo(null);
    try {
      await apiRequest<void>(`/extra-services/${serviceId}`, { method: "DELETE", token });
      setInfo("Extra service removed from panel and server");
      await loadData();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to delete service");
    } finally {
      setDeletingId(null);
    }
  }

  async function handleRefreshStatus(serviceId: number) {
    if (!token) {
      return;
    }
    setRefreshingId(serviceId);
    setError(null);
    setInfo(null);
    try {
      await apiRequest<ExtraService>(`/extra-services/${serviceId}/refresh-status`, {
        method: "POST",
        token,
      });
      setInfo("Service status refreshed");
      await loadData();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to refresh MTProxy status");
    } finally {
      setRefreshingId(null);
    }
  }

  async function handleSendEmail(service: ExtraService) {
    if (!token || !deliveryEmailInput.trim()) {
      return;
    }
    setSendingEmailServiceId(service.id);
    setError(null);
    setInfo(null);
    try {
      const result = await apiRequest<{ email: string; detail: string }>(`/extra-services/${service.id}/deliver-email`, {
        method: "POST",
        token,
        body: { email: deliveryEmailInput.trim() },
      });
      setInfo(result.detail);
      setDeliveryServiceId(null);
      setDeliveryEmailInput("");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to send service access");
    } finally {
      setSendingEmailServiceId(null);
    }
  }

  async function handleCopyLink(value: string | null | undefined) {
    if (!value) {
      setError(copy.copyFailed);
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
      setInfo(copy.copySuccess);
      setError(null);
    } catch {
      setError(copy.copyFailed);
    }
  }

  function formatDate(value: string | null) {
    if (!value) {
      return "—";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleString(locale === "ru" ? "ru-RU" : "en-US");
  }

  return (
    <ProtectedApp>
      <div className="stack">
        <section className="panel stack">
          <span className="eyebrow">{copy.eyebrow}</span>
          <h2>{copy.title}</h2>
          <p className="muted">{copy.allowedHint}</p>
          <div className="extra-service-install-grid">
            <section className="server-card stack extra-service-install-card">
              <h3>{copy.serviceTitle}</h3>
              <p className="muted">{copy.plannedHint}</p>
              <div className="extra-service-install-meta">
                <a href="https://github.com/TelegramMessenger/MTProxy" target="_blank" rel="noreferrer">
                  {copy.repoLabel}
                </a>
              </div>
              <div className="extra-service-form">
                <label className="field-label" htmlFor="mtproxy-server">{copy.server}</label>
                <select
                  id="mtproxy-server"
                  className="input"
                  value={selectedServerId}
                  onChange={(event) => setSelectedServerId(event.target.value)}
                  disabled={loading !== null || servers.length === 0}
                >
                  <option value="">{copy.selectServer}</option>
                  {servers.map((server) => (
                    <option key={server.id} value={server.id}>
                      {server.name} ({server.host})
                    </option>
                  ))}
                </select>
                <label className="field-label" htmlFor="mtproxy-domain">{copy.domain}</label>
                <input
                  id="mtproxy-domain"
                  className="input"
                  value={domainInput}
                  onChange={(event) => setDomainInput(event.target.value)}
                  disabled={loading !== null}
                  placeholder="vk.com"
                  maxLength={15}
                />
                <div className="extra-service-form-helper">
                  <p className="muted">{copy.domainHint}</p>
                  <p className="muted">{normalizedDomain.length}/15</p>
                  {domainTooLong ? <p className="error-text">Domain is too long for script-mode secret.</p> : null}
                </div>
                <div className="extra-service-form-actions">
                  <button
                    type="button"
                    className="primary-button"
                    disabled={loading !== null || !selectedServerId || selectedServerHasMtProxy || !domainInput.trim() || domainTooLong}
                    onClick={() => void handleCreateMtProxy()}
                  >
                    {loading === "mtproxy" ? copy.adding : copy.add}
                  </button>
                  {selectedServerHasMtProxy ? <p className="muted">{copy.alreadyOnServer}</p> : null}
                </div>
              </div>
            </section>
            <section className="server-card stack extra-service-install-card">
              <h3>{copy.socksTitle}</h3>
              <p className="muted">{copy.socksHint}</p>
              <div className="extra-service-install-meta">
                <a href="https://github.com/serjs/socks5-server" target="_blank" rel="noreferrer">
                  {copy.socksRepoLabel}
                </a>
              </div>
              <div className="extra-service-form">
                <label className="field-label" htmlFor="socks5-server">{copy.server}</label>
                <select
                  id="socks5-server"
                  className="input"
                  value={selectedSocksServerId}
                  onChange={(event) => setSelectedSocksServerId(event.target.value)}
                  disabled={loading !== null || servers.length === 0}
                >
                  <option value="">{copy.selectServer}</option>
                  {servers.map((server) => (
                    <option key={`socks-${server.id}`} value={server.id}>
                      {server.name} ({server.host})
                    </option>
                  ))}
                </select>
                <div className="extra-service-empty-field" aria-hidden="true" />
                <div className="extra-service-form-helper" />
                <div className="extra-service-form-actions">
                  <button
                    type="button"
                    className="primary-button"
                    disabled={loading !== null || !selectedSocksServerId || selectedServerHasSocks5}
                    onClick={() => void handleCreateSocks5()}
                  >
                    {loading === "socks5" ? copy.addingSocks : copy.addSocks}
                  </button>
                  {selectedServerHasSocks5 ? <p className="muted">{copy.socksAlreadyOnServer}</p> : null}
                </div>
              </div>
            </section>
            <section className="server-card stack extra-service-install-card">
              <h3>{copy.xrayTitle}</h3>
              <p className="muted">{copy.xrayHint}</p>
              <div className="extra-service-install-meta">
                <a href="https://github.com/XTLS/Xray-core" target="_blank" rel="noreferrer">
                  {copy.repoLabel}
                </a>
              </div>
              <div className="extra-service-form">
                <label className="field-label" htmlFor="xray-server">{copy.server}</label>
                <select
                  id="xray-server"
                  className="input"
                  value={selectedXrayServerId}
                  onChange={(event) => setSelectedXrayServerId(event.target.value)}
                  disabled={loading !== null || servers.length === 0}
                >
                  <option value="">{copy.selectServer}</option>
                  {servers.map((server) => (
                    <option key={`xray-${server.id}`} value={server.id}>
                      {server.name} ({server.host})
                    </option>
                  ))}
                </select>
                <label className="field-label" htmlFor="xray-domain">{copy.xrayServerName}</label>
                <input
                  id="xray-domain"
                  className="input"
                  value={xrayDomainInput}
                  onChange={(event) => setXrayDomainInput(event.target.value)}
                  disabled={loading !== null}
                  placeholder="www.apple.com"
                />
                <div className="extra-service-form-helper" />
                <div className="extra-service-form-actions">
                  <button
                    type="button"
                    className="primary-button"
                    disabled={loading !== null || !selectedXrayServerId || !xrayDomainInput.trim() || selectedServerHasXray}
                    onClick={() => void handleCreateXray()}
                  >
                    {loading === "xray" ? copy.addingXray : copy.addXray}
                  </button>
                  {selectedServerHasXray ? <p className="muted">{copy.xrayAlreadyOnServer}</p> : null}
                </div>
              </div>
            </section>
          </div>
        </section>

        {error ? <section className="panel error-banner">{error}</section> : null}
        {info ? <section className="panel success-banner">{info}</section> : null}

        <section className="panel stack">
          <span className="eyebrow">{copy.installed}</span>
          {mtProxyServices.length === 0 ? (
            <p className="muted">{copy.empty}</p>
          ) : (
            <div className="stack">
              {mtProxyServices.map((service) => {
                const config = service.config_json ? JSON.parse(service.config_json) as MtProxyConfig : {};
                const isDeliveryOpen = deliveryServiceId === service.id;
                return (
                  <article key={service.id} className="server-card stack">
                    <div className="server-card-header">
                      <div>
                        <h3>{copy.serviceTitle}</h3>
                        <p className="muted">
                          {service.server_name} ({service.server_host})
                        </p>
                      </div>
                      <span className="status-pill">{copy.status}: {service.status}</span>
                    </div>
                    <div className="extra-service-highlight-card">
                      <div className="extra-service-highlight-head">
                        <span className="extra-service-meta-label">{copy.mtproxyProfile}</span>
                      </div>
                      <strong>{service.public_endpoint ?? "—"}</strong>
                      <p className="muted">{copy.mtproxyAccessHint}</p>
                      <div className="extra-service-uri-box">
                        <span className="extra-service-uri-text">{config.tg_url ?? "—"}</span>
                        <button
                          type="button"
                          className="extra-service-copy-icon"
                          disabled={!config.tg_url}
                          aria-label={copy.copyLinkAria}
                          title={copy.copyLink}
                          onClick={() => void handleCopyLink(config.tg_url)}
                        >
                          <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
                            <rect x="9" y="9" width="10" height="10" rx="2" fill="none" stroke="currentColor" strokeWidth="1.8" />
                            <path d="M7 15H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v1" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                          </svg>
                        </button>
                      </div>
                    </div>
                    <div className="extra-service-meta-grid">
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.topology}</span>
                        <span>{service.topology_name ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.role}</span>
                        <span>{service.topology_role ?? "standard"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.endpoint}</span>
                        <span>{service.public_endpoint ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.stage}</span>
                        <span>{config.install_state ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.domainValue}</span>
                        <span>{config.domain ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.modeValue}</span>
                        <span>{config.image_mode ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.installJob}</span>
                        <span>{service.install_job_id ? `#${service.install_job_id} ${service.install_job_status ?? "—"}` : "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.updated}</span>
                        <span>{formatDate(service.install_job_updated_at)}</span>
                      </div>
                      <div className="extra-service-meta-item extra-service-meta-item-wide">
                        <span className="extra-service-meta-label">{copy.repo}</span>
                        <a href={config.repo_url ?? "#"} target="_blank" rel="noreferrer">
                          {config.repo_url ?? "—"}
                        </a>
                      </div>
                      <div className="extra-service-meta-item extra-service-meta-item-wide">
                        <span className="extra-service-meta-label">{copy.tgLink}</span>
                        {config.tg_url ? (
                          <a href={config.tg_url} target="_blank" rel="noreferrer">
                            {config.tg_url}
                          </a>
                        ) : (
                          <span>—</span>
                        )}
                      </div>
                      <div className="extra-service-meta-item extra-service-meta-item-wide">
                        <span className="extra-service-meta-label">{copy.task}</span>
                        <span>{service.install_job_task_id ?? "—"}</span>
                      </div>
                    </div>
                    {service.last_error ? <div className="diagnostics-box">{service.last_error}</div> : null}
                    {isDeliveryOpen ? (
                      <div className="clients-settings-body">
                        <div className="extra-service-delivery-header">
                          <strong>{copy.deliverTitle}</strong>
                          <span className="muted">{copy.deliverHint}</span>
                        </div>
                        <div className="extra-service-delivery-row">
                          <label className="field-label" htmlFor={`mtproxy-delivery-${service.id}`}>{copy.deliverEmail}</label>
                          <input
                            id={`mtproxy-delivery-${service.id}`}
                            className="input"
                            value={deliveryEmailInput}
                            onChange={(event) => setDeliveryEmailInput(event.target.value)}
                            placeholder="user@example.com"
                          />
                        </div>
                        <div className="actions-row">
                          <button
                            type="button"
                            className="primary-button"
                            disabled={sendingEmailServiceId === service.id || !deliveryEmailInput.trim()}
                            onClick={() => void handleSendEmail(service)}
                          >
                            {sendingEmailServiceId === service.id ? copy.deliverSending : copy.deliverSend}
                          </button>
                        </div>
                      </div>
                    ) : null}
                    <div className="actions-row">
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={refreshingId === service.id}
                        onClick={() => void handleRefreshStatus(service.id)}
                      >
                        {refreshingId === service.id ? copy.refreshing : copy.refresh}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => {
                          setDeliveryServiceId(service.id);
                          setDeliveryEmailInput("");
                        }}
                      >
                        {copy.deliverOpen}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={deletingId === service.id}
                        onClick={() => void handleDelete(service.id)}
                      >
                        {deletingId === service.id ? copy.removing : copy.remove}
                      </button>
                    </div>
                  </article>
                );
              })}
              {socks5Services.map((service) => {
                const config = service.config_json ? JSON.parse(service.config_json) as Socks5Config : {};
                const isDeliveryOpen = deliveryServiceId === service.id;
                return (
                  <article key={service.id} className="server-card stack">
                    <div className="server-card-header">
                      <div>
                        <h3>{copy.socksTitle}</h3>
                        <p className="muted">
                          {service.server_name} ({service.server_host})
                        </p>
                      </div>
                      <span className="status-pill">{copy.status}: {service.status}</span>
                    </div>
                    <div className="extra-service-meta-grid">
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.topology}</span>
                        <span>{service.topology_name ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.role}</span>
                        <span>{service.topology_role ?? "standard"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.endpoint}</span>
                        <span>{service.public_endpoint ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.stage}</span>
                        <span>{config.install_state ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.username}</span>
                        <span>{config.username ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.password}</span>
                        <span>{config.password ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.modeValue}</span>
                        <span>{config.image_mode ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.installJob}</span>
                        <span>{service.install_job_id ? `#${service.install_job_id} ${service.install_job_status ?? "—"}` : "—"}</span>
                      </div>
                      <div className="extra-service-meta-item extra-service-meta-item-wide">
                        <span className="extra-service-meta-label">{copy.repo}</span>
                        <a href={config.repo_url ?? "#"} target="_blank" rel="noreferrer">
                          {config.repo_url ?? "—"}
                        </a>
                      </div>
                      <div className="extra-service-meta-item extra-service-meta-item-wide">
                        <span className="extra-service-meta-label">{copy.updated}</span>
                        <span>{formatDate(service.install_job_updated_at)}</span>
                      </div>
                      <div className="extra-service-meta-item extra-service-meta-item-wide">
                        <span className="extra-service-meta-label">{copy.task}</span>
                        <span>{service.install_job_task_id ?? "—"}</span>
                      </div>
                    </div>
                    {service.last_error ? <div className="diagnostics-box">{service.last_error}</div> : null}
                    {isDeliveryOpen ? (
                      <div className="clients-settings-body">
                        <div className="extra-service-delivery-header">
                          <strong>{copy.deliverTitle}</strong>
                          <span className="muted">{copy.deliverHint}</span>
                        </div>
                        <div className="extra-service-delivery-row">
                          <label className="field-label" htmlFor={`socks5-delivery-${service.id}`}>{copy.deliverEmail}</label>
                          <input
                            id={`socks5-delivery-${service.id}`}
                            className="input"
                            value={deliveryEmailInput}
                            onChange={(event) => setDeliveryEmailInput(event.target.value)}
                            placeholder="user@example.com"
                          />
                        </div>
                        <div className="actions-row">
                          <button
                            type="button"
                            className="primary-button"
                            disabled={sendingEmailServiceId === service.id || !deliveryEmailInput.trim()}
                            onClick={() => void handleSendEmail(service)}
                          >
                            {sendingEmailServiceId === service.id ? copy.deliverSending : copy.deliverSend}
                          </button>
                        </div>
                      </div>
                    ) : null}
                    <div className="actions-row">
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={refreshingId === service.id}
                        onClick={() => void handleRefreshStatus(service.id)}
                      >
                        {refreshingId === service.id ? copy.refreshing : copy.refresh}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => {
                          setDeliveryServiceId(service.id);
                          setDeliveryEmailInput("");
                        }}
                      >
                        {copy.deliverOpen}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={deletingId === service.id}
                        onClick={() => void handleDelete(service.id)}
                      >
                        {deletingId === service.id ? copy.removing : copy.remove}
                      </button>
                    </div>
                  </article>
                );
              })}
              {xrayServices.map((service) => {
                const config = service.config_json ? JSON.parse(service.config_json) as XrayConfig : {};
                const isDeliveryOpen = deliveryServiceId === service.id;
                return (
                  <article key={service.id} className="server-card stack">
                    <div className="server-card-header">
                      <div>
                        <h3>{copy.xrayTitle}</h3>
                        <p className="muted">
                          {service.server_name} ({service.server_host})
                        </p>
                      </div>
                      <span className="status-pill">{copy.status}: {service.status}</span>
                    </div>
                    <div className="extra-service-highlight-card">
                      <div className="extra-service-highlight-head">
                        <span className="extra-service-meta-label">{copy.xrayProfile}</span>
                      </div>
                      <strong>{service.public_endpoint ?? "—"}</strong>
                      <p className="muted">{copy.xrayAccessHint}</p>
                      <div className="extra-service-uri-box">
                        <span className="extra-service-uri-text">{config.client_uri ?? "—"}</span>
                        <button
                          type="button"
                          className="extra-service-copy-icon"
                          disabled={!config.client_uri}
                          aria-label={copy.copyLinkAria}
                          title={copy.copyLink}
                          onClick={() => void handleCopyLink(config.client_uri)}
                        >
                          <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
                            <rect x="9" y="9" width="10" height="10" rx="2" fill="none" stroke="currentColor" strokeWidth="1.8" />
                            <path d="M7 15H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v1" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                          </svg>
                        </button>
                      </div>
                    </div>
                    <div className="extra-service-meta-grid">
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.topology}</span>
                        <span>{service.topology_name ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.role}</span>
                        <span>{service.topology_role ?? "standard"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.endpoint}</span>
                        <span>{service.public_endpoint ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.stage}</span>
                        <span>{config.install_state ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.xrayServerName}</span>
                        <span>{config.server_name ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.modeValue}</span>
                        <span>{config.image_mode ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.uuid}</span>
                        <span>{config.uuid ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.shortId}</span>
                        <span>{config.short_id ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item extra-service-meta-item-wide">
                        <span className="extra-service-meta-label">{copy.publicKey}</span>
                        <span>{config.public_key ?? "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.installJob}</span>
                        <span>{service.install_job_id ? `#${service.install_job_id} ${service.install_job_status ?? "—"}` : "—"}</span>
                      </div>
                      <div className="extra-service-meta-item">
                        <span className="extra-service-meta-label">{copy.updated}</span>
                        <span>{formatDate(service.install_job_updated_at)}</span>
                      </div>
                    </div>
                    {service.last_error ? <div className="diagnostics-box">{service.last_error}</div> : null}
                    {isDeliveryOpen ? (
                      <div className="clients-settings-body">
                        <div className="extra-service-delivery-header">
                          <strong>{copy.deliverTitle}</strong>
                          <span className="muted">{copy.deliverHint}</span>
                        </div>
                        <div className="extra-service-delivery-row">
                          <label className="field-label" htmlFor={`xray-delivery-${service.id}`}>{copy.deliverEmail}</label>
                          <input
                            id={`xray-delivery-${service.id}`}
                            className="input"
                            value={deliveryEmailInput}
                            onChange={(event) => setDeliveryEmailInput(event.target.value)}
                            placeholder="user@example.com"
                          />
                        </div>
                        <div className="actions-row">
                          <button
                            type="button"
                            className="primary-button"
                            disabled={sendingEmailServiceId === service.id || !deliveryEmailInput.trim()}
                            onClick={() => void handleSendEmail(service)}
                          >
                            {sendingEmailServiceId === service.id ? copy.deliverSending : copy.deliverSend}
                          </button>
                        </div>
                      </div>
                    ) : null}
                    <div className="actions-row">
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={refreshingId === service.id}
                        onClick={() => void handleRefreshStatus(service.id)}
                      >
                        {refreshingId === service.id ? copy.refreshing : copy.refresh}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => {
                          setDeliveryServiceId(service.id);
                          setDeliveryEmailInput("");
                        }}
                      >
                        {copy.deliverOpen}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={deletingId === service.id}
                        onClick={() => void handleDelete(service.id)}
                      >
                        {deletingId === service.id ? copy.removing : copy.remove}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </ProtectedApp>
  );
}
