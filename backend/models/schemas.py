"""Transport schemas and domain DTOs. Framework-free except pydantic."""
from typing import Any

from pydantic import BaseModel, Field


# --- Domain DTOs -----------------------------------------------------------

class VectorRecord(BaseModel):
    """One embedded chunk headed for the vector store."""

    embedding: list[float]
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScoredChunk(BaseModel):
    """Raw hybrid-search hit (pre-rerank)."""

    point_id: str
    score: float  # RRF fusion score — ordinal, not calibrated
    text: str
    payload: dict[str, Any] = Field(default_factory=dict)


class RetrievedChunk(BaseModel):
    """Post-rerank result handed to prompt assembly. `text` is mutated by
    context expansion (section/window), so this model stays mutable."""

    text: str
    source: str
    page_number: int | str | None = None
    score: float  # reranker relevance in [0, 1]
    point_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


# --- API schemas ------------------------------------------------------------

class QueryRequest(BaseModel):
    question: str
    documents: list[str] | None = None  # optional filter by filenames
    session_id: str | None = None       # enables conversation memory


class Citation(BaseModel):
    index: int
    text: str
    source: str
    page_number: int | str
    score: float


class QueryResponse(BaseModel):
    answer_with_refs: str
    citations: list[Citation]
    standalone_question: str
    trace_id: str
    cached: bool = False


class MinIOIngestRequest(BaseModel):
    bucket: str
    object_name: str


class IngestAccepted(BaseModel):
    job_id: str
    status: str
    status_url: str


class DeleteDocumentsRequest(BaseModel):
    object_names: list[str]
