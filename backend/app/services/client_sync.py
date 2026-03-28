from __future__ import annotations

import asyncio
import json

from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.server import Server
from app.models.topology import Topology, TopologyType
from app.models.topology_node import TopologyNode, TopologyNodeRole
from app.services.clients_table import ClientsTableService
from app.services.standard_config_adopter import StandardConfigAdopter
from app.services.topology_deployer import TopologyDeployer
from app.services.topology_renderer import RenderedConfig


class ClientSyncService:
    def __init__(self) -> None:
        self.adopter = StandardConfigAdopter()
        self.deployer = TopologyDeployer()
        self.clients_table = ClientsTableService()

    def apply_server_clients(self, db: Session, server: Server) -> None:
        if not server.live_runtime_details_json:
            return

        standard_node = (
            db.query(TopologyNode)
            .filter(
                TopologyNode.server_id == server.id,
                TopologyNode.role == TopologyNodeRole.STANDARD_VPN,
            )
            .first()
        )
        proxy_node = (
            db.query(TopologyNode)
            .filter(
                TopologyNode.server_id == server.id,
                TopologyNode.role == TopologyNodeRole.PROXY,
            )
            .first()
        )

        node = standard_node or proxy_node
        if not node:
            return

        topology = db.query(Topology).filter(Topology.id == node.topology_id).first()
        if not topology or topology.type not in {TopologyType.STANDARD, TopologyType.PROXY_EXIT}:
            return
        if topology.type == TopologyType.PROXY_EXIT and not proxy_node:
            return

        runtime_details = json.loads(server.live_runtime_details_json)
        live_config = runtime_details.get("config_preview") or ""
        if not isinstance(live_config, str) or not live_config.strip():
            raise RuntimeError("Imported server live config is missing")

        active_clients = (
            db.query(Client)
            .filter(
                Client.server_id == server.id,
                Client.topology_id == topology.id,
                Client.archived.is_(False),
            )
            .all()
        )
        merged = self.adopter.render(server, active_clients, live_config)
        runtime_details["config_preview"] = merged
        runtime_details["config_path"] = server.live_config_path
        runtime_details["peer_count"] = str(merged.count("[Peer]"))
        server.live_runtime_details_json = json.dumps(runtime_details)
        server.live_peer_count = merged.count("[Peer]")
        db.add(server)
        rendered = RenderedConfig(
            server_id=server.id,
            interface_name=server.live_interface_name or "wg0",
            remote_path=server.live_config_path,
            content=merged,
        )
        asyncio.run(self.deployer.upload_and_apply_adopted_standard(server, rendered))

        all_server_clients = (
            db.query(Client)
            .filter(
                Client.server_id == server.id,
                Client.topology_id == topology.id,
                Client.archived.is_(False),
            )
            .order_by(Client.created_at.asc(), Client.id.asc())
            .all()
        )
        if not all_server_clients:
            all_server_clients = (
                db.query(Client)
                .filter(Client.server_id == server.id, Client.archived.is_(False))
                .order_by(Client.created_at.asc(), Client.id.asc())
                .all()
            )
        existing_clients_table = asyncio.run(self.clients_table.fetch_existing(server))
        rendered_clients_table = self.clients_table.render(all_server_clients, existing_clients_table)
        rendered_clients_table = asyncio.run(self.clients_table.merge_runtime_stats(server, rendered_clients_table))
        asyncio.run(self.clients_table.upload(server, rendered_clients_table))
