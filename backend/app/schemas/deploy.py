from pydantic import BaseModel


class TopologyDeployPreview(BaseModel):
    topology_id: int
    proxy_server_id: int | None
    exit_server_ids: list[int]
    rendered_files: dict[str, str]
