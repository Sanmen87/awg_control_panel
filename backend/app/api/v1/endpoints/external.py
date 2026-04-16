import json
from datetime import datetime
from typing import Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_api_token
from app.api.v1.endpoints.clients import (
    _decorate_client,
    _hydrate_server_live_state_from_preview,
    _hydrate_server_live_state_from_remote,
    _parse_quiet_time,
)
from app.core.security import decrypt_value, encrypt_value
from app.db.session import get_db
from app.models.api_token import ApiToken
from app.models.client import Client, ClientSource
from app.models.server import Server
from app.models.topology import Topology, TopologyType
from app.models.topology_node import TopologyNode, TopologyNodeRole
from app.schemas.external import (
    ExternalClientMaterialsRead,
    ExternalClientCreateWithMaterialsRead,
    ExternalClientRead,
    ExternalClientTargetRead,
    ExternalExitTargetRead,
    ExternalServerRead,
    ExternalTopologyClientCreate,
)
from app.services.api_tokens import ApiTokenService
from app.services.audit import AuditService
from app.services.client_materials import ClientMaterialsService
from app.services.client_sync import ClientSyncService

router = APIRouter()


class _ExternalClientPayload(Protocol):
    name: str
    exit_server_id: int | None
    import_note: str | None
    expires_at: datetime | None
    quiet_hours_start: str | None
    quiet_hours_end: str | None
    quiet_hours_timezone: str | None
    traffic_limit_mb: int | None
    delivery_email: str | None
    delivery_telegram_chat_id: str | None
    delivery_telegram_username: str | None


def _require(token: ApiToken, scope: str) -> None:
    ApiTokenService().require_scope(token, scope)


def _server_ready_for_managed_clients(server: Server) -> bool:
    return bool(server.awg_detected and server.live_runtime_details_json and server.live_address_cidr)


def _topology_default_exit_id(topology: Topology, exit_nodes: list[TopologyNode]) -> int | None:
    if not exit_nodes:
        return None
    exit_ids = {node.server_id for node in exit_nodes}
    if topology.default_exit_server_id and topology.default_exit_server_id in exit_ids:
        return topology.default_exit_server_id
    return sorted(exit_nodes, key=lambda item: item.priority)[0].server_id


def _topology_create_node(topology: Topology, nodes: list[TopologyNode]) -> TopologyNode | None:
    if topology.type == TopologyType.STANDARD:
        return next((node for node in nodes if node.role == TopologyNodeRole.STANDARD_VPN), None)
    if topology.type in {TopologyType.PROXY_EXIT, TopologyType.PROXY_MULTI_EXIT}:
        return next((node for node in nodes if node.role == TopologyNodeRole.PROXY), None)
    return None


def _client_target_for_topology(
    topology: Topology,
    nodes: list[TopologyNode],
    servers_by_id: dict[int, Server],
) -> ExternalClientTargetRead | None:
    create_node = _topology_create_node(topology, nodes)
    if not create_node:
        return None
    create_server = servers_by_id.get(create_node.server_id)
    if not create_server:
        return None
    exit_nodes = sorted([node for node in nodes if node.role == TopologyNodeRole.EXIT], key=lambda item: item.priority)
    default_exit_server_id = _topology_default_exit_id(topology, exit_nodes)
    exit_servers = []
    for node in exit_nodes:
        server = servers_by_id.get(node.server_id)
        if not server:
            continue
        exit_servers.append(
            ExternalExitTargetRead(
                server_id=server.id,
                name=server.name,
                host=server.host,
                priority=node.priority,
                is_default=server.id == default_exit_server_id,
                status=server.status,
                ready_for_managed_clients=_server_ready_for_managed_clients(server),
            )
        )
    return ExternalClientTargetRead(
        topology_id=topology.id,
        topology_name=topology.name,
        topology_type=topology.type,
        topology_status=topology.status,
        create_server_id=create_server.id,
        create_server_name=create_server.name,
        create_server_host=create_server.host,
        default_exit_server_id=default_exit_server_id,
        exit_servers=exit_servers,
    )


def _resolve_external_client_context(
    db: Session,
    *,
    server_id: int | None,
    topology_id: int | None,
    exit_server_id: int | None,
) -> tuple[Server, Topology | None, int | None]:
    topology = db.query(Topology).filter(Topology.id == topology_id).first() if topology_id is not None else None
    if topology_id is not None and not topology:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology not found")

    nodes_query = db.query(TopologyNode)
    if topology:
        nodes_query = nodes_query.filter(TopologyNode.topology_id == topology.id)
    if server_id is not None:
        nodes_query = nodes_query.filter(TopologyNode.server_id == server_id)
    server_nodes = nodes_query.all()

    if server_id is not None:
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

        exit_node = next((node for node in server_nodes if node.role == TopologyNodeRole.EXIT), None)
        proxy_node = next((node for node in server_nodes if node.role == TopologyNodeRole.PROXY), None)
        if exit_node and not proxy_node:
            exit_topology = topology or db.query(Topology).filter(Topology.id == exit_node.topology_id).first()
            if exit_topology and exit_topology.type in {TopologyType.PROXY_EXIT, TopologyType.PROXY_MULTI_EXIT}:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Managed clients for proxy topologies must be created on the proxy server, not on the exit node.",
                )

        if topology is None:
            create_node = next(
                (
                    node
                    for node in server_nodes
                    if node.role in {TopologyNodeRole.STANDARD_VPN, TopologyNodeRole.PROXY}
                ),
                None,
            )
            if create_node:
                topology = db.query(Topology).filter(Topology.id == create_node.topology_id).first()
        else:
            create_node = _topology_create_node(topology, db.query(TopologyNode).filter(TopologyNode.topology_id == topology.id).all())
            if not create_node or create_node.server_id != server.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Managed clients for this topology must be created on the topology create server.",
                )
    else:
        if topology is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="server_id or topology_id is required")
        topology_nodes = db.query(TopologyNode).filter(TopologyNode.topology_id == topology.id).all()
        create_node = _topology_create_node(topology, topology_nodes)
        if not create_node:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Topology does not have a client create node")
        server = db.query(Server).filter(Server.id == create_node.server_id).first()
        if not server:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology create server not found")

    effective_exit_server_id = exit_server_id
    if topology and topology.type in {TopologyType.PROXY_EXIT, TopologyType.PROXY_MULTI_EXIT}:
        exit_nodes = (
            db.query(TopologyNode)
            .filter(TopologyNode.topology_id == topology.id, TopologyNode.role == TopologyNodeRole.EXIT)
            .order_by(TopologyNode.priority.asc())
            .all()
        )
        exit_ids = {node.server_id for node in exit_nodes}
        default_exit_server_id = _topology_default_exit_id(topology, exit_nodes)
        effective_exit_server_id = exit_server_id or default_exit_server_id
        if not exit_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Proxy topology does not have exit servers attached.",
            )
        if effective_exit_server_id not in exit_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="exit_server_id must point to an exit server attached to this topology.",
            )
    elif exit_server_id is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="exit_server_id is only supported for proxy topologies")

    return server, topology, effective_exit_server_id


def _create_external_managed_client(
    db: Session,
    *,
    server: Server,
    topology: Topology | None,
    exit_server_id: int | None,
    payload: _ExternalClientPayload,
    token: ApiToken,
) -> Client:
    server = _hydrate_server_live_state_from_preview(db, server)
    if server.awg_detected and (not server.live_runtime_details_json or not server.live_address_cidr):
        try:
            server = _hydrate_server_live_state_from_remote(db, server)
        except Exception:
            pass
    if not _server_ready_for_managed_clients(server):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Server is not ready for managed clients. Prepare the server and deploy or import the live config first.",
        )

    try:
        existing_clients = db.query(Client).filter(Client.server_id == server.id, Client.archived.is_(False)).all()
        existing_ips = [client.assigned_ip for client in existing_clients]
        materials_service = ClientMaterialsService()
        assigned_ip = materials_service.next_available_ip(server, existing_ips)
        existing_psk = None
        for existing in existing_clients:
            if existing.preshared_key_encrypted:
                existing_psk = decrypt_value(existing.preshared_key_encrypted)
                break
        materials = materials_service.build_for_server(server, payload.name, assigned_ip, existing_psk=existing_psk)

        client = Client(
            name=payload.name,
            public_key=materials.public_key,
            private_key_encrypted=encrypt_value(materials.private_key),
            preshared_key_encrypted=encrypt_value(materials.preshared_key),
            assigned_ip=materials.assigned_ip,
            status="active",
            archived=False,
            manual_disabled=False,
            source=ClientSource.GENERATED,
            server_id=server.id,
            topology_id=topology.id if topology else None,
            exit_server_id=exit_server_id,
            import_note=payload.import_note,
            expires_at=payload.expires_at,
            quiet_hours_start_minute=_parse_quiet_time(payload.quiet_hours_start),
            quiet_hours_end_minute=_parse_quiet_time(payload.quiet_hours_end),
            quiet_hours_timezone=(payload.quiet_hours_timezone or "").strip() or None,
            traffic_limit_mb=payload.traffic_limit_mb,
            delivery_email=(payload.delivery_email or "").strip() or None,
            delivery_telegram_chat_id=(payload.delivery_telegram_chat_id or "").strip() or None,
            delivery_telegram_username=(payload.delivery_telegram_username or "").strip() or None,
            config_ubuntu_encrypted=materials_service.encrypt_material(materials.ubuntu_config),
            config_amneziawg_encrypted=materials_service.encrypt_material(materials.amneziawg_config),
            config_amneziavpn_encrypted=materials_service.encrypt_material(materials.amneziavpn_config),
            qr_png_base64_encrypted=materials_service.encrypt_qr_material(materials.qr_png_base64_list),
        )
        db.add(client)
        db.flush()

        ClientSyncService().apply_server_clients(db, server)
        db.commit()
        db.refresh(client)
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    _decorate_client(client)
    AuditService().log_api_token(
        db,
        token,
        action="external.client.created",
        resource_type="client",
        resource_id=str(client.id),
        details=f"External API created managed client {client.name} on {server.name}",
        metadata_json=json.dumps(
            {
                "server_id": server.id,
                "topology_id": topology.id if topology else None,
                "exit_server_id": exit_server_id,
            }
        ),
    )
    return client


def _set_external_client_manual_status(
    db: Session,
    *,
    client: Client,
    enabled: bool,
    token: ApiToken,
) -> Client:
    client_id = client.id
    client.manual_disabled = not enabled
    if enabled:
        client.status = "disabled" if client.policy_disabled_reason else "active"
        action = "external.client.resumed"
        details = f"External API resumed client {client.name}"
    else:
        client.status = "disabled"
        action = "external.client.suspended"
        details = f"External API suspended client {client.name}"

    db.add(client)
    db.commit()

    server = db.query(Server).filter(Server.id == client.server_id).first() if client.server_id else None
    if server:
        ClientSyncService().apply_server_clients(db, server)

    refreshed_client = db.query(Client).filter(Client.id == client_id).first()
    if not refreshed_client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found after sync")

    _decorate_client(refreshed_client)
    AuditService().log_api_token(
        db,
        token,
        action=action,
        resource_type="client",
        resource_id=str(client_id),
        details=details,
        metadata_json=json.dumps({"server_id": server.id if server else None}),
    )
    return refreshed_client


@router.get("/servers", response_model=list[ExternalServerRead])
def list_external_servers(
    db: Session = Depends(get_db),
    token: ApiToken = Depends(get_current_api_token),
) -> list[Server]:
    _require(token, "servers:read")
    servers = db.query(Server).order_by(Server.created_at.desc()).all()
    for server in servers:
        setattr(server, "ready_for_managed_clients", _server_ready_for_managed_clients(server))
    return servers


@router.get("/client-targets", response_model=list[ExternalClientTargetRead])
def list_external_client_targets(
    db: Session = Depends(get_db),
    token: ApiToken = Depends(get_current_api_token),
) -> list[ExternalClientTargetRead]:
    _require(token, "servers:read")
    topologies = db.query(Topology).order_by(Topology.created_at.desc()).all()
    nodes = db.query(TopologyNode).all()
    servers = db.query(Server).all()
    nodes_by_topology: dict[int, list[TopologyNode]] = {}
    for node in nodes:
        nodes_by_topology.setdefault(node.topology_id, []).append(node)
    servers_by_id = {server.id: server for server in servers}
    targets = []
    for topology in topologies:
        target = _client_target_for_topology(topology, nodes_by_topology.get(topology.id, []), servers_by_id)
        if target:
            targets.append(target)
    return targets


@router.get("/clients", response_model=list[ExternalClientRead])
def list_external_clients(
    archived: bool = Query(False),
    server_id: int | None = Query(None),
    service_peer: bool | None = Query(None),
    db: Session = Depends(get_db),
    token: ApiToken = Depends(get_current_api_token),
) -> list[Client]:
    _require(token, "clients:read")
    query = db.query(Client).filter(Client.archived.is_(archived))
    if server_id is not None:
        query = query.filter(Client.server_id == server_id)
    if service_peer is not None:
        query = query.filter(Client.service_peer.is_(service_peer))
    clients = query.order_by(Client.created_at.desc()).all()
    for client in clients:
        _decorate_client(client)
    return clients


@router.post(
    "/topologies/{topology_id}/clients",
    response_model=ExternalClientRead | ExternalClientCreateWithMaterialsRead,
    status_code=status.HTTP_201_CREATED,
)
def create_external_topology_client(
    topology_id: int,
    payload: ExternalTopologyClientCreate,
    include_materials: bool = Query(False),
    db: Session = Depends(get_db),
    token: ApiToken = Depends(get_current_api_token),
) -> Client | ExternalClientCreateWithMaterialsRead:
    _require(token, "clients:write")
    server, topology, exit_server_id = _resolve_external_client_context(
        db,
        server_id=None,
        topology_id=topology_id,
        exit_server_id=payload.exit_server_id,
    )
    client = _create_external_managed_client(
        db,
        server=server,
        topology=topology,
        exit_server_id=exit_server_id,
        payload=payload,
        token=token,
    )
    if not include_materials:
        return client
    materials = ExternalClientMaterialsRead(**ClientMaterialsService().decrypt_materials(client))
    return ExternalClientCreateWithMaterialsRead(client=client, materials=materials)


@router.post("/clients/{client_id}/suspend", response_model=ExternalClientRead)
def suspend_external_client(
    client_id: int,
    db: Session = Depends(get_db),
    token: ApiToken = Depends(get_current_api_token),
) -> Client:
    _require(token, "clients:write")
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    return _set_external_client_manual_status(db, client=client, enabled=False, token=token)


@router.post("/clients/{client_id}/resume", response_model=ExternalClientRead)
def resume_external_client(
    client_id: int,
    db: Session = Depends(get_db),
    token: ApiToken = Depends(get_current_api_token),
) -> Client:
    _require(token, "clients:write")
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    return _set_external_client_manual_status(db, client=client, enabled=True, token=token)


@router.get("/clients/{client_id}/materials", response_model=ExternalClientMaterialsRead)
def get_external_client_materials(
    client_id: int,
    db: Session = Depends(get_db),
    token: ApiToken = Depends(get_current_api_token),
) -> ExternalClientMaterialsRead:
    _require(token, "materials:read")
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    AuditService().log_api_token(
        db,
        token,
        action="external.client.materials_read",
        resource_type="client",
        resource_id=str(client.id),
        details=f"External API read materials for client {client.name}",
    )
    return ExternalClientMaterialsRead(**ClientMaterialsService().decrypt_materials(client))


@router.delete("/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_external_client(
    client_id: int,
    db: Session = Depends(get_db),
    token: ApiToken = Depends(get_current_api_token),
) -> None:
    _require(token, "clients:write")
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    server = db.query(Server).filter(Server.id == client.server_id).first() if client.server_id else None
    client_name = client.name
    client_public_key = client.public_key
    db.delete(client)
    db.commit()

    if server:
        ClientSyncService().apply_server_clients(
            db,
            server,
            removed_public_keys={client_public_key} if client_public_key else None,
        )

    AuditService().log_api_token(
        db,
        token,
        action="external.client.deleted",
        resource_type="client",
        resource_id=str(client_id),
        details=f"External API deleted client {client_name}",
        metadata_json=json.dumps({"server_id": server.id if server else None}),
    )
