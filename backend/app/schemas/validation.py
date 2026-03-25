from pydantic import BaseModel


class TopologyValidationResponse(BaseModel):
    topology_id: int
    is_valid: bool
    errors: list[str]
    warnings: list[str]

