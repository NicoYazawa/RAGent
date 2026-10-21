"""Pydantic request/response models — fields mirror frontend src/api/types.ts (snake_case)."""
from pydantic import BaseModel, Field


class KbCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=255)


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    kb_ids: list[int] | None = None
    skip_user_persist: bool = False  # Regeneration: do not persist the user message again
    # Multimodal image references (data URL or an already stored in-app URL), up to 4
    images: list[str] | None = None


class DatasourceItemIn(BaseModel):
    source_type: str
    enabled: bool = True
    config: dict[str, str] = Field(default_factory=dict)


class DatasourceUpdate(BaseModel):
    items: list[DatasourceItemIn]


class RetrievalHitIn(BaseModel):
    title: str = ""
    snippet: str = ""
    score: float = 0.0
    meta: dict = Field(default_factory=dict)


class RetrievalLaneIn(BaseModel):
    source: str
    latency_ms: int = 0
    hits: list[RetrievalHitIn] = Field(default_factory=list)


class LaneRequest(BaseModel):
    query: str
    source: str  # vector / keyword / database
    top_k: int = 5
    kb_ids: list[int] | None = None


class FuseRequest(BaseModel):
    query: str = ""  # Used by the grader (optional; without it fusion runs but nothing is graded)
    lanes: list[RetrievalLaneIn]
    rerank: bool = False  # Rerank after fusion (requires settings.rerank_enabled)
