import time
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ChunkMetadata(BaseModel):
    chunk_id: str
    file_id: str
    sequence_number: int
    sha256_hash: str
    size: int


class ChunkData(BaseModel):
    metadata: ChunkMetadata
    data: bytes

    model_config = ConfigDict(arbitrary_types_allowed=True)


class FileMetadata(BaseModel):
    file_id: str
    filename: str
    file_size: int
    chunk_count: int
    chunk_size: int
    file_hash: str
    created_at: float = Field(default_factory=time.time)
    encryption_key_b64: Optional[str] = None
    chunks: List[ChunkMetadata] = []


class PeerInfo(BaseModel):
    peer_id: str
    ip: str
    port: int
    status: str = "active"  # active, inactive, suspect
    latency_ms: float = 0.0
    reliability_score: float = 100.0  # 0 to 100
    last_seen: float = Field(default_factory=time.time)
    successful_transfers: int = 0
    failed_transfers: int = 0
    integrity_failures: int = 0


class ChunkReplicaRecord(BaseModel):
    chunk_id: str
    file_id: str
    peer_id: str
    replica_id: str
    status: str = "active"
    created_at: float = Field(default_factory=time.time)


class MetricRecord(BaseModel):
    metric_name: str
    value: float
    timestamp: float = Field(default_factory=time.time)
    details: Optional[str] = None
