import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.client import Client
from app.models.server import Server
from app.models.topology import Topology, TopologyType
from app.models.topology_node import TopologyNode
from app.models.user import User
from app.schemas.topology_node import TopologyNodeCreate, TopologyNodeRead, TopologyNodeUpdate
from app.services.client_import import ClientImportService

router = APIRouter()


@router.get("", response_model=list[TopologyNodeRead])
def list_topology_nodes(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[TopologyNode]:
    return db.query(TopologyNode).order_by(TopologyNode.created_at.desc()).all()


@router.post("", response_model=TopologyNodeRead)
def create_topology_node(
    payload: TopologyNodeCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TopologyNode:
    server = db.query(Server).filter(Server.id == payload.server_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    if not server.ready_for_topology:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Server is not ready for topology assignment",
        )
    node = TopologyNode(**payload.model_dump())
    db.add(node)
    db.commit()
    db.refresh(node)

    topology = db.query(Topology).filter(Topology.id == payload.topology_id).first()
    if (
        topology
        and topology.type == TopologyType.STANDARD
        and payload.role.value == "standard-vpn"
        and server.config_source == "imported"
    ):
        peers = asyncio.run(ClientImportService().fetch_peers(server))
        summary = ClientImportService().import_into_db(db, server, peers)
        if summary.client_ids:
            imported_clients = db.query(Client).filter(Client.id.in_(summary.client_ids)).all()
            for client in imported_clients:
                client.topology_id = topology.id
                db.add(client)
            db.commit()
    return node


@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_topology_node(
    node_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    node = db.query(TopologyNode).filter(TopologyNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology node not found")
    db.delete(node)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{node_id}", response_model=TopologyNodeRead)
def update_topology_node(
    node_id: int,
    payload: TopologyNodeUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TopologyNode:
    node = db.query(TopologyNode).filter(TopologyNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology node not found")

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(node, field, value)

    db.add(node)
    db.commit()
    db.refresh(node)
    return node
