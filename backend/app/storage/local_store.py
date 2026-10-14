import os
from pathlib import Path
from typing import Optional
from app.config import DATA_DIR


class LocalChunkStore:
    """Manages raw/encrypted chunk storage on disk for a node."""

    def __init__(self, node_id: str, base_dir: Optional[Path] = None):
        self.node_id = node_id
        self.storage_dir = (base_dir or DATA_DIR) / f"node_{node_id[:8]}" / "chunks"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def store_chunk(self, chunk_id: str, data: bytes) -> bool:
        """Stores chunk bytes under chunk_id.dat."""
        try:
            chunk_file = self.storage_dir / f"{chunk_id}.dat"
            with open(chunk_file, "wb") as f:
                f.write(data)
            return True
        except Exception:
            return False

    def get_chunk(self, chunk_id: str) -> Optional[bytes]:
        """Retrieves chunk bytes by chunk_id."""
        chunk_file = self.storage_dir / f"{chunk_id}.dat"
        if not chunk_file.exists():
            return None
        try:
            with open(chunk_file, "rb") as f:
                return f.read()
        except Exception:
            return None

    def has_chunk(self, chunk_id: str) -> bool:
        """Checks if chunk exists on disk."""
        chunk_file = self.storage_dir / f"{chunk_id}.dat"
        return chunk_file.exists()

    def delete_chunk(self, chunk_id: str) -> bool:
        """Deletes chunk from disk if present."""
        chunk_file = self.storage_dir / f"{chunk_id}.dat"
        if chunk_file.exists():
            try:
                chunk_file.unlink()
                return True
            except Exception:
                return False
        return False
