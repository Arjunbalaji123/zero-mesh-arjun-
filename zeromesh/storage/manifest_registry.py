"""
ZeroMesh Storage — Manifest Registry
======================================
Tracks uploaded file manifests so they can be retrieved by manifest_id.
Manifests describe how a file was chunked and which content_ids to fetch.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import aiosqlite

from zeromesh.core.chunker import ChunkMeta, FileManifest

_DDL = """
CREATE TABLE IF NOT EXISTS manifests (
    manifest_id TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    total_size  INTEGER NOT NULL,
    chunk_size  INTEGER NOT NULL,
    chunks_json TEXT NOT NULL,
    uploaded_at REAL  NOT NULL
);
"""


class ManifestRegistry:
    """
    Async SQLite registry for FileManifests.

    Usage::

        registry = ManifestRegistry(data_dir=Path("./data"))
        await registry.open()
        await registry.save(manifest)
        m = await registry.get("deadbeef...")
        await registry.close()
    """

    def __init__(self, data_dir: Path) -> None:
        self._db_path = Path(data_dir) / "manifests.db"
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute(_DDL)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def save(self, manifest: FileManifest) -> None:
        """Persist a manifest. Idempotent for the same manifest_id."""
        self._assert_open()
        chunks_json = json.dumps([
            {"index": c.index, "content_id": c.content_id, "size": c.size}
            for c in manifest.chunks
        ])
        await self._db.execute(  # type: ignore[union-attr]
            "INSERT OR IGNORE INTO manifests "
            "(manifest_id, filename, total_size, chunk_size, chunks_json, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                manifest.manifest_id,
                manifest.filename,
                manifest.total_size,
                manifest.chunk_size,
                chunks_json,
                time.time(),
            ),
        )
        await self._db.commit()  # type: ignore[union-attr]

    async def get(self, manifest_id: str) -> FileManifest | None:
        """Retrieve a FileManifest by its ID, or None if not found."""
        self._assert_open()
        async with self._db.execute(  # type: ignore[union-attr]
            "SELECT filename, total_size, chunk_size, chunks_json FROM manifests "
            "WHERE manifest_id = ?",
            (manifest_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None

        filename, total_size, chunk_size, chunks_json = row
        raw_chunks = json.loads(chunks_json)
        chunk_metas = [
            ChunkMeta(index=c["index"], content_id=c["content_id"], size=c["size"])
            for c in raw_chunks
        ]
        return FileManifest(
            filename=filename,
            total_size=total_size,
            chunk_size=chunk_size,
            chunks=chunk_metas,
        )

    async def list_all(self) -> list[tuple[str, str, int]]:
        """Return (manifest_id, filename, total_size) for all stored manifests."""
        self._assert_open()
        async with self._db.execute(  # type: ignore[union-attr]
            "SELECT manifest_id, filename, total_size FROM manifests ORDER BY uploaded_at DESC"
        ) as cur:
            return [(r[0], r[1], r[2]) for r in await cur.fetchall()]

    async def delete(self, manifest_id: str) -> bool:
        self._assert_open()
        cursor = await self._db.execute(  # type: ignore[union-attr]
            "DELETE FROM manifests WHERE manifest_id = ?", (manifest_id,)
        )
        await self._db.commit()  # type: ignore[union-attr]
        return cursor.rowcount > 0

    def _assert_open(self) -> None:
        if self._db is None:
            raise RuntimeError("ManifestRegistry not open. Call await registry.open() first.")
