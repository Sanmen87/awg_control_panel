import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import decrypt_value, encrypt_value
from app.db.session import get_db
from app.models.client import Client, ClientSource
from app.models.server import Server
from app.models.topology_node import TopologyNode, TopologyNodeRole
from app.models.user import User
from app.schemas.client import (
    ClientCreate,
    ClientDeliveryRequest,
    ClientImportRequest,
    ClientImportResponse,
    ClientMaterialsRead,
    ClientRead,
    ManagedClientCreate,
    ClientUpdate,
)
from app.services.audit import AuditService
from app.services.client_import import ClientImportService
from app.services.client_materials import ClientMaterialsService
from app.services.client_sync import ClientSyncService
from app.services.delivery import DeliveryService

router = APIRouter()


def _format_quiet_time(value: int | None) -> str | None:
    if value is None:
        return None
    hours = value // 60
    minutes = value % 60
    return f"{hours:02d}:{minutes:02d}"


def _parse_quiet_time(value: str | None) -> int | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    parts = raw.split(":")
    if len(parts) != 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid quiet hours time format")
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid quiet hours time format") from exc
    if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid quiet hours time value")
    return hours * 60 + minutes


def _decorate_client(client: Client) -> Client:
    setattr(client, "private_key_available", bool(client.private_key_encrypted))
    setattr(
        client,
        "materials_available",
        bool(client.config_ubuntu_encrypted or client.config_amneziawg_encrypted or client.config_amneziavpn_encrypted),
    )
    setattr(client, "quiet_hours_start", _format_quiet_time(client.quiet_hours_start_minute))
    setattr(client, "quiet_hours_end", _format_quiet_time(client.quiet_hours_end_minute))
    return client


@router.get("", response_model=list[ClientRead])
def list_clients(
    archived: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Client]:
    clients = (
        db.query(Client)
        .filter(Client.archived.is_(archived))
        .order_by(Client.created_at.desc())
        .all()
    )
    for client in clients:
        _decorate_client(client)
    return clients


@router.post("", response_model=ClientRead)
def create_client(
    payload: ClientCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Client:
    client_data = payload.model_dump(exclude={"private_key"})
    client = Client(**client_data)
    if payload.private_key:
        client.private_key_encrypted = encrypt_value(payload.private_key)
    db.add(client)
    db.commit()
    db.refresh(client)
    setattr(client, "private_key_available", bool(client.private_key_encrypted))
    setattr(client, "materials_available", False)
    AuditService().log(
        db,
        action="client.created",
        resource_type="client",
        resource_id=str(client.id),
        details=f"Client {client.name} created",
        user_id=current_user.id,
    )
    return client


@router.post("/managed", response_model=ClientRead)
def create_managed_client(
    payload: ManagedClientCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Client:
    server = db.query(Server).filter(Server.id == payload.server_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    if not server.awg_detected or not server.live_address_cidr:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Server is not ready for managed clients")

    existing_clients = db.query(Client).filter(Client.server_id == server.id).all()
    existing_clients = [client for client in existing_clients if not client.archived]
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
        topology_id=payload.topology_id,
        import_note=payload.import_note,
        expires_at=payload.expires_at,
        quiet_hours_start_minute=_parse_quiet_time(payload.quiet_hours_start),
        quiet_hours_end_minute=_parse_quiet_time(payload.quiet_hours_end),
        quiet_hours_timezone=(payload.quiet_hours_timezone or "").strip() or None,
        traffic_limit_mb=payload.traffic_limit_mb,
        config_ubuntu_encrypted=materials_service.encrypt_material(materials.ubuntu_config),
        config_amneziawg_encrypted=materials_service.encrypt_material(materials.amneziawg_config),
        config_amneziavpn_encrypted=materials_service.encrypt_material(materials.amneziavpn_config),
        qr_png_base64_encrypted=materials_service.encrypt_qr_material(materials.qr_png_base64_list),
    )
    db.add(client)
    db.commit()
    db.refresh(client)

    if client.topology_id is None:
        standard_node = (
            db.query(TopologyNode)
            .filter(
                TopologyNode.server_id == server.id,
                TopologyNode.role == TopologyNodeRole.STANDARD_VPN,
            )
            .first()
        )
        if standard_node:
            client.topology_id = standard_node.topology_id
            db.add(client)
            db.commit()
            db.refresh(client)

    ClientSyncService().apply_server_clients(db, server)
    _decorate_client(client)
    AuditService().log(
        db,
        action="client.managed_created",
        resource_type="client",
        resource_id=str(client.id),
        details=f"Managed client {client.name} created on {server.name}",
        user_id=current_user.id,
    )
    return client


@router.patch("/{client_id}", response_model=ClientRead)
def update_client(
    client_id: int,
    payload: ClientUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Client:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    client.name = payload.name
    if payload.status is not None:
        if payload.status == "disabled":
            client.manual_disabled = True
            client.status = "disabled"
        elif payload.status == "active":
            client.manual_disabled = False
            client.status = "disabled" if client.policy_disabled_reason else "active"
        else:
            client.status = payload.status
    client.import_note = payload.import_note
    if "delivery_email" in payload.model_fields_set:
        client.delivery_email = (payload.delivery_email or "").strip() or None
    if "delivery_telegram_chat_id" in payload.model_fields_set:
        client.delivery_telegram_chat_id = (payload.delivery_telegram_chat_id or "").strip() or None
    if "delivery_telegram_username" in payload.model_fields_set:
        client.delivery_telegram_username = (payload.delivery_telegram_username or "").strip() or None
    if "expires_at" in payload.model_fields_set:
        client.expires_at = payload.expires_at
    if "quiet_hours_start" in payload.model_fields_set:
        client.quiet_hours_start_minute = _parse_quiet_time(payload.quiet_hours_start)
    if "quiet_hours_end" in payload.model_fields_set:
        client.quiet_hours_end_minute = _parse_quiet_time(payload.quiet_hours_end)
    if "quiet_hours_timezone" in payload.model_fields_set:
        client.quiet_hours_timezone = (payload.quiet_hours_timezone or "").strip() or None
    if "traffic_limit_mb" in payload.model_fields_set:
        client.traffic_limit_mb = payload.traffic_limit_mb
    db.add(client)
    db.commit()
    db.refresh(client)
    _decorate_client(client)
    if client.server_id:
        server = db.query(Server).filter(Server.id == client.server_id).first()
        if server:
            ClientSyncService().apply_server_clients(db, server)
    AuditService().log(
        db,
        action="client.updated",
        resource_type="client",
        resource_id=str(client.id),
        details=f"Client {client.name} updated",
        user_id=current_user.id,
    )
    return client


@router.get("/{client_id}/materials", response_model=ClientMaterialsRead)
def get_client_materials(
    client_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ClientMaterialsRead:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    return ClientMaterialsRead(**ClientMaterialsService().decrypt_materials(client))


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    server = db.query(Server).filter(Server.id == client.server_id).first() if client.server_id else None
    client_name = client.name
    db.delete(client)
    db.commit()

    if server:
        ClientSyncService().apply_server_clients(db, server)

    AuditService().log(
        db,
        action="client.deleted",
        resource_type="client",
        resource_id=str(client_id),
        details=f"Client {client_name} deleted",
        user_id=current_user.id,
    )


@router.post("/import", response_model=ClientImportResponse)
def import_clients(
    payload: ClientImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClientImportResponse:
    server = db.query(Server).filter(Server.id == payload.server_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

    peers = asyncio.run(ClientImportService().fetch_peers(server))
    summary = ClientImportService().import_into_db(db, server, peers)
    standard_nodes = (
        db.query(TopologyNode)
        .filter(
            TopologyNode.server_id == server.id,
            TopologyNode.role == TopologyNodeRole.STANDARD_VPN,
        )
        .all()
    )
    topology_ids = [node.topology_id for node in standard_nodes]
    if topology_ids:
        imported_clients = db.query(Client).filter(Client.id.in_(summary.client_ids)).all()
        target_topology_id = topology_ids[0]
        for client in imported_clients:
            client.topology_id = target_topology_id
            db.add(client)
        db.commit()
    AuditService().log(
        db,
        action="clients.imported",
        resource_type="server",
        resource_id=str(server.id),
        details=f"Imported peers from {server.name}: {summary.imported_count} new, {summary.updated_count} updated",
        user_id=current_user.id,
    )
    return ClientImportResponse(
        imported_count=summary.imported_count,
        updated_count=summary.updated_count,
        skipped_count=summary.skipped_count,
        client_ids=summary.client_ids,
    )


@router.post("/{client_id}/deliver-configs")
def deliver_client_configs(
    client_id: int,
    payload: ClientDeliveryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    result = DeliveryService().deliver_client_configs(db, client, payload.channels)
    AuditService().log(
        db,
        action="client.configs.delivered",
        resource_type="client",
        resource_id=str(client.id),
        details=f"Config delivery requested for {client.name}: {result}",
        user_id=current_user.id,
    )
    return result
