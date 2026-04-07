import asyncio
import json
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_agent, get_current_user
from app.db.session import get_db
from app.models.agent_node import AgentNode
from app.models.agent_task import AgentTask
from app.models.server import Server
from app.models.user import User
from app.schemas.agent import (
    AgentEnrollRead,
    AgentHeartbeatPayload,
    AgentNodeRead,
    AgentTaskAckPayload,
    AgentTaskCreate,
    AgentTaskRead,
)
from app.services.audit import AuditService
from app.services.server_agent import ServerAgentService

router = APIRouter()
ALLOWED_AGENT_TASK_TYPES = {
    "noop",
    "collect-runtime-snapshot",
    "collect-traffic-counters",
    "read-clients-table",
    "enforce-client-policies",
    "inspect-standard-runtime",
}


@router.get("", response_model=list[AgentNodeRead])
def list_agents(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[AgentNode]:
    return db.query(AgentNode).order_by(AgentNode.created_at.desc()).all()


@router.post("/enroll/{server_id}", response_model=AgentEnrollRead, status_code=status.HTTP_201_CREATED)
def enroll_agent(
    server_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentNode:
    server = db.query(Server).filter(Server.id == server_id).first()
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

    agent = db.query(AgentNode).filter(AgentNode.server_id == server_id).first()
    token = secrets.token_urlsafe(32)
    if agent is None:
        agent = AgentNode(server_id=server_id, token=token, status="enrolled")
    else:
        agent.token = token
        agent.status = "enrolled"
        agent.last_error = None
    db.add(agent)
    db.commit()
    db.refresh(agent)

    AuditService().log(
        db,
        action="agent.enrolled",
        resource_type="server",
        resource_id=str(server_id),
        details=f"Agent enrolled for server {server.name}",
        user_id=current_user.id,
    )
    return agent


@router.post("/install/{server_id}", response_model=AgentNodeRead, status_code=status.HTTP_202_ACCEPTED)
def install_agent(
    server_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentNode:
    server = db.query(Server).filter(Server.id == server_id).first()
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

    service = ServerAgentService()
    agent = service.ensure_enrolled(db, server)
    asyncio.run(service.install(server, agent))

    payload = asyncio.run(service.fetch_local_status(server))
    now = datetime.now(UTC)
    if payload is not None:
        agent.status = str(payload.get("status") or "online")
        agent.local_state_json = json_dumps(payload.get("local_state"))
        agent.capabilities_json = json_dumps(payload.get("capabilities"))
        agent.version = str(payload.get("version") or agent.version or "")
        agent.last_seen_at = now
        agent.last_sync_at = now
        agent.last_error = None
    else:
        agent.status = "offline"
        agent.last_error = "Agent installed, but local status file is unavailable"
    db.add(agent)
    db.commit()
    db.refresh(agent)

    AuditService().log(
        db,
        action="agent.installed",
        resource_type="server",
        resource_id=str(server_id),
        details=f"Agent installed for server {server.name}",
        user_id=current_user.id,
    )
    return agent


@router.post("/sync/heartbeat", response_model=AgentNodeRead)
def agent_heartbeat(
    payload: AgentHeartbeatPayload,
    db: Session = Depends(get_db),
    agent: AgentNode = Depends(get_current_agent),
) -> AgentNode:
    now = datetime.now(UTC)
    agent.status = "online"
    agent.version = payload.version
    agent.capabilities_json = payload.capabilities_json
    agent.local_state_json = payload.local_state_json
    agent.last_error = payload.last_error
    agent.last_seen_at = now
    agent.last_sync_at = now
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.get("/sync/tasks", response_model=list[AgentTaskRead])
def agent_pull_tasks(
    db: Session = Depends(get_db),
    agent: AgentNode = Depends(get_current_agent),
) -> list[AgentTask]:
    tasks = (
        db.query(AgentTask)
        .filter(AgentTask.agent_id == agent.id, AgentTask.status.in_(["pending", "running"]))
        .order_by(AgentTask.created_at.asc(), AgentTask.id.asc())
        .all()
    )
    now = datetime.now(UTC)
    changed = False
    for task in tasks:
        if task.status == "pending":
            task.status = "running"
            task.started_at = now
            db.add(task)
            changed = True
    if changed:
        db.commit()
        for task in tasks:
            db.refresh(task)
    return tasks


@router.post("/sync/tasks/{task_id}/ack", response_model=AgentTaskRead)
def agent_ack_task(
    task_id: int,
    payload: AgentTaskAckPayload,
    db: Session = Depends(get_db),
    agent: AgentNode = Depends(get_current_agent),
) -> AgentTask:
    task = db.query(AgentTask).filter(AgentTask.id == task_id, AgentTask.agent_id == agent.id).first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent task not found")
    task.status = payload.status
    task.result_json = payload.result_json
    task.last_error = payload.last_error
    task.completed_at = datetime.now(UTC) if payload.status in {"succeeded", "failed"} else None
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("/{server_id}/tasks", response_model=list[AgentTaskRead])
def list_agent_tasks(
    server_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[AgentTask]:
    return (
        db.query(AgentTask)
        .filter(AgentTask.server_id == server_id)
        .order_by(AgentTask.created_at.desc(), AgentTask.id.desc())
        .all()
    )


@router.post("/{server_id}/tasks", response_model=AgentTaskRead, status_code=status.HTTP_201_CREATED)
def create_agent_task(
    server_id: int,
    payload: AgentTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentTask:
    agent = db.query(AgentNode).filter(AgentNode.server_id == server_id).first()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent is not enrolled for this server")
    if payload.task_type not in ALLOWED_AGENT_TASK_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported agent task type")
    task = AgentTask(
        agent_id=agent.id,
        server_id=server_id,
        task_type=payload.task_type,
        payload_json=payload.payload_json,
        status="pending",
        requested_by_user_id=current_user.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("/{server_id}/local-status", response_model=AgentNodeRead)
def fetch_agent_local_status(
    server_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AgentNode:
    server = db.query(Server).filter(Server.id == server_id).first()
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    agent = db.query(AgentNode).filter(AgentNode.server_id == server_id).first()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent is not enrolled for this server")
    payload = asyncio.run(ServerAgentService().fetch_local_status(server))
    now = datetime.now(UTC)
    if payload is not None:
        agent.status = str(payload.get("status") or "online")
        agent.local_state_json = json_dumps(payload.get("local_state"))
        agent.capabilities_json = json_dumps(payload.get("capabilities"))
        agent.version = str(payload.get("version") or agent.version or "")
        agent.last_seen_at = now
        agent.last_sync_at = now
        agent.last_error = None
    else:
        agent.status = "offline"
        agent.last_error = "Local agent status file is unavailable"
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.post("/{server_id}/local-tasks", response_model=AgentTaskRead, status_code=status.HTTP_201_CREATED)
def queue_local_agent_task(
    server_id: int,
    payload: AgentTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentTask:
    server = db.query(Server).filter(Server.id == server_id).first()
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    agent = db.query(AgentNode).filter(AgentNode.server_id == server_id).first()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent is not enrolled for this server")
    if payload.task_type not in ALLOWED_AGENT_TASK_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported agent task type")

    task = AgentTask(
        agent_id=agent.id,
        server_id=server_id,
        task_type=payload.task_type,
        payload_json=payload.payload_json,
        status="pending",
        requested_by_user_id=current_user.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    task_payload = None
    if payload.payload_json:
        try:
            parsed = json.loads(payload.payload_json)
            if isinstance(parsed, dict):
                task_payload = parsed
        except json.JSONDecodeError:
            task_payload = {"raw": payload.payload_json}
    asyncio.run(ServerAgentService().enqueue_local_task(server, str(task.id), payload.task_type, task_payload))
    return task


@router.post("/{server_id}/sync-local-results", response_model=list[AgentTaskRead])
def sync_local_agent_results(
    server_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[AgentTask]:
    server = db.query(Server).filter(Server.id == server_id).first()
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    agent = db.query(AgentNode).filter(AgentNode.server_id == server_id).first()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent is not enrolled for this server")

    results = asyncio.run(ServerAgentService().fetch_local_results(server))
    updated: list[AgentTask] = []
    now = datetime.now(UTC)
    for item in results:
        task_id_raw = item.get("id")
        if task_id_raw is None:
            continue
        try:
            task_id = int(task_id_raw)
        except (TypeError, ValueError):
            continue
        task = db.query(AgentTask).filter(AgentTask.id == task_id, AgentTask.agent_id == agent.id).first()
        if task is None:
            continue
        task.status = str(item.get("status") or task.status)
        result_payload = item.get("result")
        task.result_json = json_dumps(result_payload) if result_payload is not None else task.result_json
        task.last_error = str(item.get("last_error")) if item.get("last_error") else None
        task.completed_at = now if task.status in {"succeeded", "failed"} else task.completed_at
        db.add(task)
        updated.append(task)
    agent.last_sync_at = now
    db.add(agent)
    db.commit()
    for task in updated:
        db.refresh(task)
    return updated


def json_dumps(value: object | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)
