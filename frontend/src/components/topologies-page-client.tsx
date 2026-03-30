"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import { apiRequest } from "./api";
import { ProtectedApp } from "./protected-app";
import { useAuth } from "./auth-context";
import { useLocale } from "./locale-context";

type Server = {
  id: number;
  name: string;
  host: string;
  ready_for_topology: boolean;
  config_source: string;
  live_interface_name: string | null;
  live_config_path: string | null;
  live_address_cidr: string | null;
  live_listen_port: number | null;
  live_peer_count: number | null;
  live_runtime_details_json: string | null;
};

type LivePeer = {
  public_key: string;
  allowed_ips?: string;
  endpoint?: string;
};

type LiveRuntimeDetails = {
  runtime?: string;
  docker_container?: string;
  docker_image?: string;
  config_preview?: string;
  peers?: LivePeer[];
};

type Topology = {
  id: number;
  name: string;
  type: string;
  status: string;
  active_exit_server_id: number | null;
  failover_config_json: string | null;
  metadata_json: string | null;
};

type TopologyNode = {
  id: number;
  topology_id: number;
  server_id: number;
  role: string;
  priority: number;
  status: string;
};

type DeployPreview = {
  topology_id: number;
  proxy_server_id: number | null;
  exit_server_ids: number[];
  rendered_files: Record<string, string>;
};

type ValidationResult = {
  topology_id: number;
  is_valid: boolean;
  errors: string[];
  warnings: string[];
};

type Job = {
  id: number;
  job_type?: string;
  status: string;
  topology_id?: number | null;
  result_message?: string | null;
};

type FailoverForm = {
  retries: number;
  interval_sec: number;
  timeout_sec: number;
  failback_successes: number;
  auto_failback: boolean;
};

const DEFAULT_FAILOVER: FailoverForm = {
  retries: 3,
  interval_sec: 5,
  timeout_sec: 3,
  failback_successes: 2,
  auto_failback: false
};

const initialCreateForm = {
  name: "",
  type: "standard"
};

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function parseFailoverConfig(raw: string | null): FailoverForm {
  if (!raw) {
    return DEFAULT_FAILOVER;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<FailoverForm>;
    return {
      retries: Number(parsed.retries ?? DEFAULT_FAILOVER.retries),
      interval_sec: Number(parsed.interval_sec ?? DEFAULT_FAILOVER.interval_sec),
      timeout_sec: Number(parsed.timeout_sec ?? DEFAULT_FAILOVER.timeout_sec),
      failback_successes: Number(parsed.failback_successes ?? DEFAULT_FAILOVER.failback_successes),
      auto_failback: Boolean(parsed.auto_failback ?? DEFAULT_FAILOVER.auto_failback)
    };
  } catch {
    return DEFAULT_FAILOVER;
  }
}

function stringifyFailoverConfig(config: FailoverForm): string {
  return JSON.stringify(config);
}

function parseTopologyMetadata(raw: string | null): { awg_profile_name?: string } {
  if (!raw) {
    return {};
  }
  try {
    const parsed = JSON.parse(raw) as { awg_profile_name?: string };
    return typeof parsed === "object" && parsed ? parsed : {};
  } catch {
    return {};
  }
}

export function TopologiesPageClient() {
  const { token, logout } = useAuth();
  const { locale } = useLocale();
  const [servers, setServers] = useState<Server[]>([]);
  const [topologies, setTopologies] = useState<Topology[]>([]);
  const [nodes, setNodes] = useState<TopologyNode[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedTopologyId, setSelectedTopologyId] = useState<number | null>(null);
  const [createForm, setCreateForm] = useState(initialCreateForm);
  const [editorName, setEditorName] = useState("");
  const [editorType, setEditorType] = useState("standard");
  const [editorAwgProfile, setEditorAwgProfile] = useState("compatible");
  const [failoverForm, setFailoverForm] = useState<FailoverForm>(DEFAULT_FAILOVER);
  const [standardServerId, setStandardServerId] = useState("");
  const [proxyServerId, setProxyServerId] = useState("");
  const [exitAssignments, setExitAssignments] = useState<Array<{ nodeId?: number; server_id: string; priority: number }>>([]);
  const [preview, setPreview] = useState<DeployPreview | null>(null);
  const [validationByTopology, setValidationByTopology] = useState<Record<number, ValidationResult>>({});
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const copy = locale === "ru"
    ? {
        title: "Пошаговая сборка topology и безопасное переключение между типами.",
        refresh: "Обновить",
        listTitle: "Топологии",
        createTitle: "Новая topology",
        noTopologies: "Топологии еще не созданы.",
        create: "Создать",
        editorTitle: "Редактор topology",
        chooseTopology: "Выберите topology слева или создайте новую.",
        steps: {
          identity: "Шаг 1. Тип и имя",
          servers: "Шаг 2. Назначение серверов",
          failover: "Шаг 3. Failover",
          review: "Шаг 4. Проверка и deploy"
        },
        fields: {
          name: "Имя",
          type: "Тип topology",
          awgProfile: "AWG-профиль",
          standardServer: "Основной сервер",
          proxyServer: "Входной proxy",
          exitServer: "Exit сервер",
          priority: "Приоритет переключения",
          retries: "Сколько ошибок подряд до переключения",
          interval: "Как часто проверять exit, сек",
          timeout: "Сколько ждать ответ, сек",
          failback: "Сколько успешных проверок до возврата",
          autoFailback: "Возвращаться на основной exit автоматически"
        },
        types: {
          standard: "Обычный VPN сервер",
          proxyExit: "Proxy + 1 exit",
          proxyMultiExit: "Proxy + несколько exit"
        },
        descriptions: {
          standard: "Один сервер без промежуточных exit-узлов.",
          proxyExit: "Один proxy и один exit. Подходит как первый failover-сценарий.",
          proxyMultiExit: "Один proxy и несколько exit. Можно задать общий exit по умолчанию и переопределять выход для отдельных peer-ов."
        },
        profiles: {
          compatible: "compatible"
        },
        actions: {
          saveTopology: "Сохранить topology",
          changeType: "Сменить тип topology",
          deleteTopology: "Удалить topology",
          addExit: "Добавить exit",
          saveServers: "Сохранить назначение серверов",
          saveFailover: "Сохранить failover",
          preview: "Предпросмотр конфигурации",
          deploy: "Применить",
          removeExit: "Удалить exit"
        },
        helper: {
          readyOnly: "В списке доступны только серверы, готовые для topology.",
          typeChange:
            "При смене типа панель старается сохранить совместимые узлы и приводит роли к новому сценарию. Если что-то лишнее, вы увидите это на шаге проверки.",
          awgProfile:
            "Профиль обфускации задаётся на уровне topology. После его смены нужно заново применить topology, чтобы сервер и generated-клиенты получили новые параметры.",
          failover:
            "Эти настройки использует локальный агент на proxy. Он сам проверяет доступность exit и переключает маршрут даже если панель недоступна. Для большинства сценариев подходят значения 3 / 10 / 3 / 2.",
          defaultExit:
            "Основным считается exit с самым высоким приоритетом переключения. Именно он будет использоваться для peer-ов без индивидуального переопределения.",
          validationOk: "Topology валидна и готова к preview/deploy.",
          previewEmpty: "Предпросмотр еще не запрашивался."
        },
        status: {
          draft: "черновик",
          pending: "ожидает",
          applied: "применена",
          error: "ошибка",
          valid: "валидна",
          invalid: "невалидна",
          activeExit: "активный exit",
          exits: "exit узлов"
        },
        labels: {
          warnings: "Предупреждения",
          errors: "Ошибки",
          currentNodes: "Текущие узлы",
          previewFiles: "Сгенерированные файлы",
          importedConfig: "Импортированный текущий конфиг",
          runtime: "runtime"
        },
        helperImported:
          "Этот сервер уже работает со своей конфигурацией. Топология будет опираться на импортированный live config, а не на новый шаблон панели.",
        noImportedConfig: "Для выбранного сервера live config еще не импортирован.",
        latestJob: "Последняя deploy-задача"
      }
    : {
        title: "Build topologies step by step and convert them safely between supported types.",
        refresh: "Refresh",
        listTitle: "Topologies",
        createTitle: "New topology",
        noTopologies: "No topologies created yet.",
        create: "Create",
        editorTitle: "Topology editor",
        chooseTopology: "Select a topology on the left or create a new one.",
        steps: {
          identity: "Step 1. Name and type",
          servers: "Step 2. Server assignment",
          failover: "Step 3. Failover",
          review: "Step 4. Validation and deploy"
        },
        fields: {
          name: "Name",
          type: "Topology type",
          awgProfile: "AWG profile",
          standardServer: "Primary server",
          proxyServer: "Ingress proxy",
          exitServer: "Exit server",
          priority: "Failover priority",
          retries: "Consecutive failures before switch",
          interval: "How often to check the exit, sec",
          timeout: "How long to wait for a reply, sec",
          failback: "Successful checks before failback",
          autoFailback: "Return to the primary exit automatically"
        },
        types: {
          standard: "Standard VPN server",
          proxyExit: "Proxy + 1 exit",
          proxyMultiExit: "Proxy + multiple exits"
        },
        descriptions: {
          standard: "Single AWG node without intermediate exit servers.",
          proxyExit: "One proxy and one exit. Good starting point for failover topology.",
          proxyMultiExit: "One proxy with multiple exits. You can set a default exit and override the exit for specific peers."
        },
        profiles: {
          compatible: "compatible"
        },
        actions: {
          saveTopology: "Save topology",
          changeType: "Change topology type",
          deleteTopology: "Delete topology",
          addExit: "Add exit",
          saveServers: "Save server assignment",
          saveFailover: "Save failover",
          preview: "Configuration preview",
          deploy: "Deploy",
          removeExit: "Remove exit"
        },
        helper: {
          readyOnly: "Only servers marked ready for topology are available here.",
          typeChange:
            "When you change the topology type, the panel keeps compatible nodes and adjusts roles to the new scenario where possible.",
          awgProfile:
            "Obfuscation profile is configured on topology level. Re-deploy the topology after changing it so the server and generated clients receive updated parameters.",
          failover:
            "These settings are used by the local agent on the proxy. It checks exit health and switches routes even if the panel is unavailable. Safe defaults for most setups are 3 / 10 / 3 / 2.",
          defaultExit:
            "The highest-priority exit becomes the primary one automatically. Peers without an explicit override use that exit.",
          validationOk: "Topology is valid and ready for preview/deploy.",
          previewEmpty: "Preview has not been requested yet."
        },
        status: {
          draft: "draft",
          pending: "pending",
          applied: "applied",
          error: "error",
          valid: "valid",
          invalid: "invalid",
          activeExit: "active exit",
          exits: "exit nodes"
        },
        labels: {
          warnings: "Warnings",
          errors: "Errors",
          currentNodes: "Current nodes",
          previewFiles: "Rendered files",
          importedConfig: "Imported live config",
          runtime: "runtime"
        },
        helperImported:
          "This server is already running with its own configuration. The topology will use the imported live config instead of generating a fresh panel template.",
        noImportedConfig: "The selected server does not have an imported live config yet.",
        queued: "Last queued job",
        latestJob: "Latest deploy job",
        confirmDelete: "Delete this topology completely? All nodes inside it will be removed as well."
      };

  const readyServers = useMemo(
    () => servers.filter((server) => server.ready_for_topology),
    [servers]
  );

  async function loadData() {
    if (!token) {
      return;
    }
    try {
      const [nextServers, nextTopologies, nextNodes, nextJobs] = await Promise.all([
        apiRequest<Server[]>("/servers", { token }),
        apiRequest<Topology[]>("/topologies", { token }),
        apiRequest<TopologyNode[]>("/topology-nodes", { token }),
        apiRequest<Job[]>("/jobs", { token })
      ]);
      setServers(nextServers);
      setTopologies(nextTopologies);
      setNodes(nextNodes);
      setJobs(nextJobs);
      setError(null);

      if (!selectedTopologyId && nextTopologies.length > 0) {
        setSelectedTopologyId(nextTopologies[0].id);
      } else if (selectedTopologyId && !nextTopologies.some((item) => item.id === selectedTopologyId)) {
        setSelectedTopologyId(nextTopologies[0]?.id ?? null);
      }
    } catch (nextError) {
      const message = nextError instanceof Error ? nextError.message : "Failed to load topology data";
      setError(message);
      if (message.includes("401")) {
        logout();
      }
    }
  }

  async function loadValidation(topologyIds: number[]) {
    if (!token || topologyIds.length === 0) {
      setValidationByTopology({});
      return;
    }
    try {
      const results = await Promise.all(
        topologyIds.map((topologyId) =>
          apiRequest<ValidationResult>(`/topologies/${topologyId}/validation`, { token })
        )
      );
      setValidationByTopology(
        results.reduce<Record<number, ValidationResult>>((acc, item) => {
          acc[item.topology_id] = item;
          return acc;
        }, {})
      );
    } catch {
      // Validation is supportive only.
    }
  }

  useEffect(() => {
    void loadData();
  }, [token]);

  useEffect(() => {
    void loadValidation(topologies.map((item) => item.id));
  }, [token, topologies]);

  const nodesByTopology = useMemo(() => {
    return nodes.reduce<Record<number, TopologyNode[]>>((acc, node) => {
      if (!acc[node.topology_id]) {
        acc[node.topology_id] = [];
      }
      acc[node.topology_id].push(node);
      return acc;
    }, {});
  }, [nodes]);

  const selectedTopology = useMemo(
    () => topologies.find((item) => item.id === selectedTopologyId) ?? null,
    [selectedTopologyId, topologies]
  );

  const selectedNodes = useMemo(() => {
    if (!selectedTopologyId) {
      return [];
    }
    return [...(nodesByTopology[selectedTopologyId] ?? [])].sort((left, right) => left.priority - right.priority);
  }, [nodesByTopology, selectedTopologyId]);

  const latestDeployJob = useMemo(() => {
    if (!selectedTopology) {
      return null;
    }
    return jobs.find((job) => job.job_type === "deploy-topology" && job.topology_id === selectedTopology.id) ?? null;
  }, [jobs, selectedTopology]);

  function parseRuntimeDetails(server: Server | null): LiveRuntimeDetails | null {
    if (!server?.live_runtime_details_json) {
      return null;
    }
    try {
      return JSON.parse(server.live_runtime_details_json) as LiveRuntimeDetails;
    } catch {
      return null;
    }
  }

  const selectedStandardServer = useMemo(() => {
    const serverId = Number(standardServerId);
    if (!serverId) {
      return null;
    }
    return servers.find((server) => server.id === serverId) ?? null;
  }, [servers, standardServerId]);

  const selectedStandardServerDetails = useMemo(
    () => parseRuntimeDetails(selectedStandardServer),
    [selectedStandardServer]
  );

  useEffect(() => {
    if (!selectedTopology) {
      setEditorName("");
      setEditorType("standard");
      setEditorAwgProfile("compatible");
      setFailoverForm(DEFAULT_FAILOVER);
      setStandardServerId("");
      setProxyServerId("");
      setExitAssignments([]);
      return;
    }

    setEditorName(selectedTopology.name);
    setEditorType(selectedTopology.type);
    setEditorAwgProfile(parseTopologyMetadata(selectedTopology.metadata_json).awg_profile_name ?? "compatible");
    setFailoverForm(parseFailoverConfig(selectedTopology.failover_config_json));

    const standardNode = selectedNodes.find((node) => node.role === "standard-vpn");
    const proxyNode = selectedNodes.find((node) => node.role === "proxy");
    const exitNodes = selectedNodes.filter((node) => node.role === "exit");

    setStandardServerId(standardNode ? String(standardNode.server_id) : "");
    setProxyServerId(proxyNode ? String(proxyNode.server_id) : "");
    setExitAssignments(
      exitNodes.map((node) => ({
        nodeId: node.id,
        server_id: String(node.server_id),
        priority: node.priority
      }))
    );
    setPreview(null);
    setInfo(null);
  }, [selectedTopology, selectedNodes]);

  function serverLabel(serverId: number) {
    const server = servers.find((item) => item.id === serverId);
    return server ? `${server.name} (${server.host})` : `#${serverId}`;
  }

  function validationState(topologyId: number) {
    return validationByTopology[topologyId] ?? null;
  }

  async function createTopology(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }
    setSaving(true);
    try {
      const created = await apiRequest<Topology>("/topologies", {
        method: "POST",
        token,
        body: {
          name: createForm.name,
          type: createForm.type,
          failover_config_json: stringifyFailoverConfig(DEFAULT_FAILOVER),
          metadata_json: JSON.stringify({ awg_profile_name: "compatible" })
        }
      });
      setCreateForm(initialCreateForm);
      await loadData();
      setSelectedTopologyId(created.id);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to create topology");
    } finally {
      setSaving(false);
    }
  }

  async function saveTopologyIdentity() {
    if (!token || !selectedTopology) {
      return;
    }
    setSaving(true);
    try {
      await apiRequest<Topology>(`/topologies/${selectedTopology.id}`, {
        method: "PATCH",
        token,
        body: {
          name: editorName,
          default_exit_server_id: null,
          failover_config_json: stringifyFailoverConfig(failoverForm),
          metadata_json: JSON.stringify({ awg_profile_name: editorAwgProfile })
        }
      });
      await loadData();
      setInfo(null);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to update topology");
    } finally {
      setSaving(false);
    }
  }

  async function removeNode(nodeId: number) {
    if (!token) {
      return;
    }
    await apiRequest<void>(`/topology-nodes/${nodeId}`, {
      method: "DELETE",
      token
    });
  }

  async function createNode(topologyId: number, serverId: number, role: string, priority: number) {
    if (!token) {
      return;
    }
    await apiRequest<TopologyNode>("/topology-nodes", {
      method: "POST",
      token,
      body: {
        topology_id: topologyId,
        server_id: serverId,
        role,
        priority,
        status: "pending"
      }
    });
  }

  async function updateNode(nodeId: number, role: string, priority: number) {
    if (!token) {
      return;
    }
    await apiRequest<TopologyNode>(`/topology-nodes/${nodeId}`, {
      method: "PATCH",
      token,
      body: {
        role,
        priority
      }
    });
  }

  async function changeTopologyType(nextType: string) {
    if (!token || !selectedTopology) {
      return;
    }
    setSaving(true);
    try {
      const currentNodes = [...selectedNodes];
      const proxyNode = currentNodes.find((node) => node.role === "proxy");
      const standardNode = currentNodes.find((node) => node.role === "standard-vpn");
      const exitNodes = currentNodes.filter((node) => node.role === "exit").sort((left, right) => left.priority - right.priority);

      await apiRequest<Topology>(`/topologies/${selectedTopology.id}`, {
        method: "PATCH",
        token,
        body: {
          type: nextType
        }
      });

      if (nextType === "standard") {
        const keeper = standardNode ?? proxyNode ?? exitNodes[0] ?? currentNodes[0];
        for (const node of currentNodes) {
          if (!keeper || node.id !== keeper.id) {
            await removeNode(node.id);
          }
        }
        if (keeper) {
          await updateNode(keeper.id, "standard-vpn", 10);
        }
      } else if (nextType === "proxy-exit" || nextType === "proxy-multi-exit") {
        const keeperProxy = proxyNode ?? standardNode ?? currentNodes[0];
        if (keeperProxy) {
          await updateNode(keeperProxy.id, "proxy", 10);
        }

        const candidateExits = exitNodes.length > 0 ? exitNodes : currentNodes.filter((node) => keeperProxy && node.id !== keeperProxy.id);
        const keeperExit = candidateExits[0];

        for (const node of currentNodes) {
          if (keeperProxy && node.id === keeperProxy.id) {
            continue;
          }
          if (keeperExit && node.id === keeperExit.id) {
            await updateNode(node.id, "exit", 10);
            continue;
          }
          if (nextType === "proxy-exit") {
            await removeNode(node.id);
            continue;
          }
          if (node.role !== "exit") {
            await removeNode(node.id);
          }
        }
      }

      await loadData();
      setEditorType(nextType);
      setInfo(null);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to change topology type");
    } finally {
      setSaving(false);
    }
  }

  async function deleteTopology(topologyId: number) {
    if (!token) {
      return;
    }
    if (!window.confirm(copy.confirmDelete)) {
      return;
    }

    setSaving(true);
    try {
      await apiRequest<void>(`/topologies/${topologyId}`, {
        method: "DELETE",
        token
      });
      if (selectedTopologyId === topologyId) {
        setSelectedTopologyId(null);
      }
      setPreview(null);
      setInfo(null);
      await loadData();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to delete topology");
    } finally {
      setSaving(false);
    }
  }

  async function saveServerAssignments() {
    if (!token || !selectedTopology) {
      return;
    }
    setSaving(true);
    try {
      if (editorType === "standard") {
        const targetServerId = Number(standardServerId);
        const standardNodes = selectedNodes.filter((node) => node.role === "standard-vpn");
        const otherNodes = selectedNodes.filter((node) => node.role !== "standard-vpn");

        for (const node of otherNodes) {
          await removeNode(node.id);
        }

        if (!targetServerId) {
          throw new Error(locale === "ru" ? "Выберите сервер для standard topology" : "Choose a server for standard topology");
        }

        const existing = standardNodes[0];
        if (existing) {
          if (existing.server_id !== targetServerId) {
            await removeNode(existing.id);
            await createNode(selectedTopology.id, targetServerId, "standard-vpn", 10);
          } else {
            await updateNode(existing.id, "standard-vpn", 10);
          }
        } else {
          await createNode(selectedTopology.id, targetServerId, "standard-vpn", 10);
        }

      } else {
        const targetProxyServerId = Number(proxyServerId);
        if (!targetProxyServerId) {
          throw new Error(locale === "ru" ? "Выберите proxy сервер" : "Choose a proxy server");
        }

        const proxyNodes = selectedNodes.filter((node) => node.role === "proxy");
        const standardNodes = selectedNodes.filter((node) => node.role === "standard-vpn");
        const allExitNodes = selectedNodes.filter((node) => node.role === "exit");

        for (const node of standardNodes) {
          await removeNode(node.id);
        }

        const existingProxy = proxyNodes[0];
        if (existingProxy) {
          if (existingProxy.server_id !== targetProxyServerId) {
            await removeNode(existingProxy.id);
            await createNode(selectedTopology.id, targetProxyServerId, "proxy", 10);
          } else {
            await updateNode(existingProxy.id, "proxy", 10);
          }
        } else {
          await createNode(selectedTopology.id, targetProxyServerId, "proxy", 10);
        }

        const normalizedExits = exitAssignments.filter((item) => item.server_id);
        const keepNodeIds = new Set<number>();

        for (const assignment of normalizedExits) {
          const serverId = Number(assignment.server_id);
          if (!serverId) {
            continue;
          }
          if (assignment.nodeId) {
            keepNodeIds.add(assignment.nodeId);
            await updateNode(assignment.nodeId, "exit", assignment.priority);
          } else {
            await createNode(selectedTopology.id, serverId, "exit", assignment.priority);
          }
        }

        for (const node of allExitNodes) {
          if (!keepNodeIds.has(node.id) && !normalizedExits.some((item) => item.nodeId === node.id)) {
            await removeNode(node.id);
          }
        }

      }

      await loadData();
      setInfo(null);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to save server assignment");
    } finally {
      setSaving(false);
    }
  }

  async function saveFailoverSettings() {
    if (!token || !selectedTopology) {
      return;
    }
    setSaving(true);
    try {
      await apiRequest<Topology>(`/topologies/${selectedTopology.id}`, {
        method: "PATCH",
        token,
        body: {
          failover_config_json: stringifyFailoverConfig(failoverForm)
        }
      });
      await loadData();
      setInfo(null);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to save failover settings");
    } finally {
      setSaving(false);
    }
  }

  async function requestPreview() {
    if (!token || !selectedTopology) {
      return;
    }
    try {
      const nextPreview = await apiRequest<DeployPreview>(`/topologies/${selectedTopology.id}/deploy-preview`, { token });
      setPreview(nextPreview);
      setInfo(null);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to get preview");
    }
  }

  async function requestDeploy() {
    if (!token || !selectedTopology) {
      return;
    }
    try {
      setSaving(true);
      setError(null);
      const job = await apiRequest<Job>(`/topologies/${selectedTopology.id}/deploy`, {
        method: "POST",
        token
      });
      setInfo(`${copy.queued}: #${job.id}`);

      let finalJob = job;
      for (let attempt = 0; attempt < 80; attempt += 1) {
        await sleep(1500);
        finalJob = await apiRequest<Job>(`/jobs/${job.id}`, { token });
        await loadData();
        if (finalJob.status === "succeeded") {
          setInfo(finalJob.result_message || `${copy.queued}: #${job.id}`);
          return;
        }
        if (finalJob.status === "failed") {
          throw new Error(finalJob.result_message || "Topology deploy failed");
        }
      }

      setInfo(
        locale === "ru"
          ? `Задача #${job.id} всё ещё выполняется. Открой Jobs для подробностей.`
          : `Job #${job.id} is still running. Open Jobs for details.`
      );
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to deploy topology");
    } finally {
      setSaving(false);
    }
  }

  function addExitRow() {
    setExitAssignments((current) => [...current, { server_id: "", priority: current.length * 10 + 10 }]);
  }

  function updateExitRow(index: number, patch: Partial<{ server_id: string; priority: number }>) {
    setExitAssignments((current) =>
      current.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item))
    );
  }

  function removeExitRow(index: number) {
    setExitAssignments((current) => current.filter((_, itemIndex) => itemIndex !== index));
  }

  return (
    <ProtectedApp>
      <div className="page-header">
        <div>
          <span className="eyebrow">Topologies</span>
          <h2>{copy.title}</h2>
        </div>
        <button type="button" className="secondary-button" onClick={() => void loadData()}>
          {copy.refresh}
        </button>
      </div>

      {error ? <div className="error-box">{error}</div> : null}
      {info ? <div className="info-box">{info}</div> : null}

      <section className="topology-layout">
        <aside className="topology-sidebar panel-card">
          <span className="eyebrow">{copy.listTitle}</span>
          <div className="topology-list">
            {topologies.length === 0 ? (
              <div className="empty-state">{copy.noTopologies}</div>
            ) : (
              topologies.map((topology) => {
                const validation = validationState(topology.id);
                const topologyNodes = nodesByTopology[topology.id] ?? [];
                const exitCount = topologyNodes.filter((node) => node.role === "exit").length;
                return (
                  <button
                    key={topology.id}
                    type="button"
                    className={`topology-list-item${selectedTopologyId === topology.id ? " active" : ""}`}
                    onClick={() => setSelectedTopologyId(topology.id)}
                  >
                    <strong>{topology.name}</strong>
                    <span>{topology.type}</span>
                    <span>
                      {copy.status[topology.status as keyof typeof copy.status] ?? topology.status}
                      {" · "}
                      {validation?.is_valid ? copy.status.valid : copy.status.invalid}
                    </span>
                    <span>
                      {copy.status.exits}: {exitCount}
                    </span>
                    {topology.active_exit_server_id ? (
                      <span>
                        {copy.status.activeExit}: {serverLabel(topology.active_exit_server_id)}
                      </span>
                    ) : null}
                  </button>
                );
              })
            )}
          </div>

          <div className="topology-create">
            <span className="eyebrow">{copy.createTitle}</span>
            <form className="field-stack" onSubmit={createTopology}>
              <label className="field">
                <span>{copy.fields.name}</span>
                <input
                  value={createForm.name}
                  onChange={(event) => setCreateForm({ ...createForm, name: event.target.value })}
                  required
                />
              </label>
              <label className="field">
                <span>{copy.fields.type}</span>
                <select
                  value={createForm.type}
                  onChange={(event) => setCreateForm({ ...createForm, type: event.target.value })}
                >
                  <option value="standard">{copy.types.standard}</option>
                  <option value="proxy-exit">{copy.types.proxyExit}</option>
                  <option value="proxy-multi-exit">{copy.types.proxyMultiExit}</option>
                </select>
              </label>
              <button type="submit" className="primary-button" disabled={saving}>
                {copy.create}
              </button>
            </form>
          </div>
        </aside>

        <div className="content-panel">
          {!selectedTopology ? (
            <div className="panel-card">{copy.chooseTopology}</div>
          ) : (
            <>
              <section className="panel-card wizard-step">
                <div className="step-header">
                  <div>
                    <span className="eyebrow">{copy.steps.identity}</span>
                    <h3>{selectedTopology.name}</h3>
                  </div>
                  <span className="status-badge status-pending">
                    {copy.status[selectedTopology.status as keyof typeof copy.status] ?? selectedTopology.status}
                  </span>
                </div>
                <p>{copy.helper.typeChange}</p>
                <div className="info-box">{copy.helper.awgProfile}</div>
                <div className="form-grid compact-form-grid">
                  <label className="field">
                    <span>{copy.fields.name}</span>
                    <input value={editorName} onChange={(event) => setEditorName(event.target.value)} />
                  </label>
                  <label className="field">
                    <span>{copy.fields.type}</span>
                    <select value={editorType} onChange={(event) => setEditorType(event.target.value)}>
                      <option value="standard">{copy.types.standard}</option>
                      <option value="proxy-exit">{copy.types.proxyExit}</option>
                      <option value="proxy-multi-exit">{copy.types.proxyMultiExit}</option>
                    </select>
                  </label>
                  <label className="field">
                    <span>{copy.fields.awgProfile}</span>
                    <select value={editorAwgProfile} onChange={(event) => setEditorAwgProfile(event.target.value)}>
                      <option value="compatible">{copy.profiles.compatible}</option>
                    </select>
                  </label>
                </div>
                <div className="topology-type-card">
                  <strong>
                    {editorType === "proxy-exit"
                      ? copy.types.proxyExit
                      : editorType === "proxy-multi-exit"
                        ? copy.types.proxyMultiExit
                        : copy.types.standard}
                  </strong>
                  <p>
                    {editorType === "proxy-exit"
                      ? copy.descriptions.proxyExit
                      : editorType === "proxy-multi-exit"
                        ? copy.descriptions.proxyMultiExit
                        : copy.descriptions.standard}
                  </p>
                </div>
                <div className="action-row">
                  <button type="button" className="secondary-button" onClick={() => void saveTopologyIdentity()} disabled={saving}>
                    {copy.actions.saveTopology}
                  </button>
                  {editorType !== selectedTopology.type ? (
                    <button type="button" className="primary-button" onClick={() => void changeTopologyType(editorType)} disabled={saving}>
                      {copy.actions.changeType}
                    </button>
                  ) : null}
                  <button type="button" className="secondary-button" onClick={() => void deleteTopology(selectedTopology.id)} disabled={saving}>
                    {copy.actions.deleteTopology}
                  </button>
                </div>
              </section>

              <section className="panel-card wizard-step">
                <span className="eyebrow">{copy.steps.servers}</span>
                <p>{copy.helper.readyOnly}</p>
                {editorType === "standard" ? (
                  <div className="field-stack">
                    <label className="field">
                      <span>{copy.fields.standardServer}</span>
                      <select value={standardServerId} onChange={(event) => setStandardServerId(event.target.value)}>
                        <option value="">-</option>
                        {readyServers.map((server) => (
                          <option key={server.id} value={server.id}>
                            {server.name} ({server.host})
                          </option>
                        ))}
                      </select>
                    </label>
                    {selectedStandardServer ? (
                      selectedStandardServer.config_source === "imported" ? (
                        <div className="node-summary">
                          <span className="eyebrow">{copy.labels.importedConfig}</span>
                          <div className="info-box">{copy.helperImported}</div>
                          <div className="server-meta">
                            {selectedStandardServerDetails?.runtime ? <span>{copy.labels.runtime}: {selectedStandardServerDetails.runtime}</span> : null}
                            {selectedStandardServer.live_interface_name ? <span>interface: {selectedStandardServer.live_interface_name}</span> : null}
                            {selectedStandardServer.live_address_cidr ? <span>subnet: {selectedStandardServer.live_address_cidr}</span> : null}
                            {selectedStandardServer.live_listen_port ? <span>port: {selectedStandardServer.live_listen_port}</span> : null}
                            {selectedStandardServer.live_peer_count !== null ? <span>peers: {selectedStandardServer.live_peer_count}</span> : null}
                          </div>
                          {selectedStandardServer.live_config_path ? <div className="info-box">{selectedStandardServer.live_config_path}</div> : null}
                          {selectedStandardServerDetails?.config_preview ? (
                            <details className="preview-item" open>
                              <summary>{copy.labels.importedConfig}</summary>
                              <pre className="log-box">{selectedStandardServerDetails.config_preview}</pre>
                            </details>
                          ) : null}
                        </div>
                      ) : (
                        <div className="info-box">{copy.noImportedConfig}</div>
                      )
                    ) : null}
                  </div>
                ) : (
                  <div className="field-stack">
                    <label className="field">
                      <span>{copy.fields.proxyServer}</span>
                      <select value={proxyServerId} onChange={(event) => setProxyServerId(event.target.value)}>
                        <option value="">-</option>
                        {readyServers.map((server) => (
                          <option key={server.id} value={server.id}>
                            {server.name} ({server.host})
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className="exit-list">
                      {exitAssignments.map((assignment, index) => (
                        <div key={assignment.nodeId ?? `new-${index}`} className="exit-row">
                          <label className="field">
                            <span>{copy.fields.exitServer}</span>
                            <select
                              value={assignment.server_id}
                              onChange={(event) => updateExitRow(index, { server_id: event.target.value })}
                            >
                              <option value="">-</option>
                              {readyServers.map((server) => (
                                <option key={server.id} value={server.id}>
                                  {server.name} ({server.host})
                                </option>
                              ))}
                            </select>
                          </label>
                          <label className="field">
                            <span>{copy.fields.priority}</span>
                            <input
                              type="number"
                              value={assignment.priority}
                              onChange={(event) => updateExitRow(index, { priority: Number(event.target.value) || 10 })}
                            />
                          </label>
                          <button type="button" className="secondary-button" onClick={() => removeExitRow(index)}>
                            {copy.actions.removeExit}
                          </button>
                        </div>
                      ))}
                    </div>
                    <div className="info-box">{copy.helper.defaultExit}</div>
                    <div className="action-row">
                      <button type="button" className="secondary-button" onClick={addExitRow}>
                        {copy.actions.addExit}
                      </button>
                    </div>
                  </div>
                )}

                {selectedNodes.length > 0 ? (
                  <div className="node-summary">
                    <span className="eyebrow">{copy.labels.currentNodes}</span>
                    <div className="server-meta">
                      {selectedNodes.map((node) => (
                        <span key={node.id}>
                          {serverLabel(node.server_id)} · {node.role} · {copy.fields.priority} {node.priority}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="action-row">
                  <button type="button" className="primary-button" onClick={() => void saveServerAssignments()} disabled={saving}>
                    {copy.actions.saveServers}
                  </button>
                </div>
              </section>

              {editorType !== "standard" ? (
                <section className="panel-card wizard-step">
                  <span className="eyebrow">{copy.steps.failover}</span>
                  <p>{copy.helper.failover}</p>
                  <div className="form-grid compact-form-grid">
                    <label className="field">
                      <span>{copy.fields.retries}</span>
                      <input
                        type="number"
                        value={failoverForm.retries}
                        onChange={(event) => setFailoverForm({ ...failoverForm, retries: Number(event.target.value) || 1 })}
                      />
                    </label>
                    <label className="field">
                      <span>{copy.fields.interval}</span>
                      <input
                        type="number"
                        value={failoverForm.interval_sec}
                        onChange={(event) => setFailoverForm({ ...failoverForm, interval_sec: Number(event.target.value) || 1 })}
                      />
                    </label>
                    <label className="field">
                      <span>{copy.fields.timeout}</span>
                      <input
                        type="number"
                        value={failoverForm.timeout_sec}
                        onChange={(event) => setFailoverForm({ ...failoverForm, timeout_sec: Number(event.target.value) || 1 })}
                      />
                    </label>
                    <label className="field">
                      <span>{copy.fields.failback}</span>
                      <input
                        type="number"
                        value={failoverForm.failback_successes}
                        onChange={(event) => setFailoverForm({ ...failoverForm, failback_successes: Number(event.target.value) || 1 })}
                      />
                    </label>
                    <label className="field checkbox-field field-wide">
                      <input
                        type="checkbox"
                        checked={failoverForm.auto_failback}
                        onChange={(event) => setFailoverForm({ ...failoverForm, auto_failback: event.target.checked })}
                      />
                      <span>{copy.fields.autoFailback}</span>
                    </label>
                  </div>
                  <div className="action-row">
                    <button type="button" className="primary-button" onClick={() => void saveFailoverSettings()} disabled={saving}>
                      {copy.actions.saveFailover}
                    </button>
                  </div>
                </section>
              ) : null}

              <section className="panel-card wizard-step">
                <span className="eyebrow">{copy.steps.review}</span>
                {editorType === "standard" && selectedStandardServer?.config_source === "imported" ? (
                  <div className="node-summary">
                    <span className="eyebrow">{copy.labels.importedConfig}</span>
                    <div className="info-box">{copy.helperImported}</div>
                    <div className="server-meta">
                      <span>{selectedStandardServer.name}</span>
                      {selectedStandardServerDetails?.runtime ? <span>{copy.labels.runtime}: {selectedStandardServerDetails.runtime}</span> : null}
                      {selectedStandardServer.live_interface_name ? <span>interface: {selectedStandardServer.live_interface_name}</span> : null}
                      {selectedStandardServer.live_address_cidr ? <span>subnet: {selectedStandardServer.live_address_cidr}</span> : null}
                      {selectedStandardServer.live_listen_port ? <span>port: {selectedStandardServer.live_listen_port}</span> : null}
                      {selectedStandardServer.live_peer_count !== null ? <span>peers: {selectedStandardServer.live_peer_count}</span> : null}
                    </div>
                  </div>
                ) : null}
                {validationState(selectedTopology.id)?.is_valid ? (
                  <div className="info-box">{copy.helper.validationOk}</div>
                ) : null}
                {validationState(selectedTopology.id)?.errors?.length ? (
                  <div className="error-box">
                    <strong>{copy.labels.errors}</strong>
                    <div className="validation-list">
                      {validationState(selectedTopology.id)?.errors.map((item) => (
                        <span key={item}>{item}</span>
                      ))}
                    </div>
                  </div>
                ) : null}
                {validationState(selectedTopology.id)?.warnings?.length ? (
                  <div className="info-box">
                    <strong>{copy.labels.warnings}</strong>
                    <div className="validation-list">
                      {validationState(selectedTopology.id)?.warnings.map((item) => (
                        <span key={item}>{item}</span>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="action-row">
                  <button type="button" className="secondary-button" onClick={() => void requestPreview()}>
                    {copy.actions.preview}
                  </button>
                  <button type="button" className="primary-button" onClick={() => void requestDeploy()}>
                    {copy.actions.deploy}
                  </button>
                </div>

                {latestDeployJob ? (
                  <div className="node-summary">
                    <span className="eyebrow">{copy.latestJob}</span>
                    <div className="server-meta">
                      <span>#{latestDeployJob.id}</span>
                      <span
                        className={
                          latestDeployJob.status === "succeeded"
                            ? "status-badge status-succeeded"
                            : latestDeployJob.status === "failed"
                              ? "status-badge status-failed"
                              : "status-badge status-pending"
                        }
                      >
                        {latestDeployJob.status}
                      </span>
                    </div>
                    {latestDeployJob.result_message ? <pre className="log-box">{latestDeployJob.result_message}</pre> : null}
                  </div>
                ) : null}

                <div className="preview-box">
                  <span className="eyebrow">{copy.labels.previewFiles}</span>
                  {!preview || preview.topology_id !== selectedTopology.id ? (
                    <div className="empty-state">{copy.helper.previewEmpty}</div>
                  ) : (
                    Object.entries(preview.rendered_files).map(([path, content]) => (
                      <details key={path} className="preview-item">
                        <summary>{path}</summary>
                        <pre className="log-box">{content}</pre>
                      </details>
                    ))
                  )}
                </div>
              </section>
            </>
          )}
        </div>
      </section>
    </ProtectedApp>
  );
}
