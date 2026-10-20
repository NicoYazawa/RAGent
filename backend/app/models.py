"""Pydantic 请求/响应模型 — 字段逐一对齐前端 src/api/types.ts（snake_case）"""
from pydantic import BaseModel, Field


class KbCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=255)


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    kb_ids: list[int] | None = None
    skip_user_persist: bool = False  # 重新生成场景：不重复落用户消息
    # 多模态图片引用列表（data URL 或已落盘站内 URL），最多 4 张
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
    query: str = ""  # 供 Grader 评估用（可选，缺省时仅融合不评估细节）
    lanes: list[RetrievalLaneIn]
    rerank: bool = False  # 融合后是否走精排（需 settings.rerank_enabled 开启）
