"""
ZeroMesh Storage — Local Chunk Store
======================================
Persists encrypted chunks to disk and indexes them in SQLite.

Design
------
- Each chunk's raw (encrypted) bytes are stored as a flat file under
  ``data_dir/chunks/<first2chars>/<content_id>.chunk``
  The two-char prefix subdirectory (like git objects) limits the number of
  files per directory to ~65536 max, avoiding filesystem lookup slowdowns.

- An SQLite index tracks metadata: content_id, size, stored_at, access_count.
  aiosqlite is used for non-blocking async access from the asyncio event loop.

- The store is content-addressed: the filename IS the content_id (SHA-256 hex),
  so we can always verify integrity by re-hashing on read.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

# ─── Schema ───────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS chunks (
    content_id   TEXT PRIMARY KEY,
    size_bytes   INTEGER NOT NULL,
    stored_at    REAL    NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0
);
"""


# ─── Chunk Metadata ───────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class StoredChunkMeta:
    content_id:   str
    size_bytes:   int
    stored_at:    float
    access_count: int


# ─── Store ────────────────────────────────────────────────────────────────────

class LocalChunkStore:
    """
    Async persistent store for encrypted chunk bytes.

    Usage::

        store = LocalChunkStore(data_dir=Path("./data"))
        await store.open()
        await store.put("deadbeef...", nonce=b"...", ciphertext=b"...")
        nonce, ct = await store.get("deadbeef...")
        await store.close()

    The ``put`` method stores the raw wire bytes (nonce || ciphertext).
    The ``get`` method returns them split back out.
    """

    NONCE_SIZE = 12  # AES-GCM 96-bit nonce

    def __init__(self, data_dir: Path) -> None:
        self._dir = Path(data_dir)
        self._chunks_dir = self._dir / "chunks"
        self._db_path = self._dir / "index.db"
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        """Create directories and initialise the SQLite schema."""
        self._chunks_dir.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute(_DDL)
        await self._db.commit()

    async def close(self) -> None:
        """Flush and close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    # ── Write ─────────────────────────────────────────────────────

    async def put(
        self,
        content_id: str,
        nonce: bytes,
        ciphertext: bytes,
    ) -> None:
        """
        Persist an encrypted chunk.

        Idempotent: if content_id already exists the call is a no-op
        (content-addressed storage guarantees the bytes are identical).

        Args:
            content_id: SHA-256 hex of the *plaintext* chunk.
            nonce:      12-byte AES-GCM nonce.
            ciphertext: AES-GCM ciphertext + 16-byte authentication tag.
        """
        self._assert_open()
        if await self.exists(content_id):
            return

        raw = nonce + ciphertext
        path = self._chunk_path(content_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: write to .tmp then rename
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(raw)
        tmp.rename(path)

        await self._db.execute(  # type: ignore[union-attr]
            "INSERT OR IGNORE INTO chunks (content_id, size_bytes, stored_at) "
            "VALUES (?, ?, ?)",
            (content_id, len(ciphertext), time.time()),
        )
        await self._db.commit()  # type: ignore[union-attr]

    # ── Read ──────────────────────────────────────────────────────

    async def get(self, content_id: str) -> tuple[bytes, bytes] | None:
        """
        Retrieve an encrypted chunk.

        Returns:
            (nonce, ciphertext) tuple, or None if not found.
        """
        self._assert_open()
        path = self._chunk_path(content_id)
        if not path.exists():
            return None

        raw = await asyncio.get_event_loop().run_in_executor(None, path.read_bytes)
        nonce = raw[: self.NONCE_SIZE]
        ciphertext = raw[self.NONCE_SIZE :]

        # Update access counter
        await self._db.execute(  # type: ignore[union-attr]
            "UPDATE chunks SET access_count = access_count + 1 WHERE content_id = ?",
            (content_id,),
        )
        await self._db.commit()  # type: ignore[union-attr]
        return nonce, ciphertext

    # ── Existence / Deletion ──────────────────────────────────────

    async def exists(self, content_id: str) -> bool:
        """True if the chunk is stored locally."""
        return self._chunk_path(content_id).exists()

    async def has(self, content_id: str) -> bool:
        """Alias for exists()."""
        return await self.exists(content_id)

    async def delete(self, content_id: str) -> bool:
        """
        Remove a chunk from disk and the index.
        Returns True if deleted, False if not found.
        """
        self._assert_open()
        path = self._chunk_path(content_id)
        if not path.exists():
            return False
        path.unlink()
        await self._db.execute(  # type: ignore[union-attr]
            "DELETE FROM chunks WHERE content_id = ?", (content_id,)
        )
        await self._db.commit()  # type: ignore[union-attr]
        return True

    # ── Query ─────────────────────────────────────────────────────

    async def list_all(self) -> list[StoredChunkMeta]:
        """Return metadata for every stored chunk."""
        self._assert_open()
        async with self._db.execute(  # type: ignore[union-attr]
            "SELECT content_id, size_bytes, stored_at, access_count FROM chunks "
            "ORDER BY stored_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
        return [StoredChunkMeta(*row) for row in rows]

    async def total_chunks(self) -> int:
        """Count of locally stored chunks."""
        self._assert_open()
        async with self._db.execute("SELECT COUNT(*) FROM chunks") as cur:  # type: ignore[union-attr]
            row = await cur.fetchone()
        return row[0] if row else 0

    async def total_bytes(self) -> int:
        """Total ciphertext bytes stored."""
        self._assert_open()
        async with self._db.execute("SELECT SUM(size_bytes) FROM chunks") as cur:  # type: ignore[union-attr]
            row = await cur.fetchone()
        if row is None or row[0] is None:
            return 0
        return int(row[0])

    # ── Helpers ───────────────────────────────────────────────────

    def _chunk_path(self, content_id: str) -> Path:
        """Two-level prefix path: chunks/<ab>/<abcdef...>.chunk"""
        return self._chunks_dir / content_id[:2] / f"{content_id}.chunk"

    def _assert_open(self) -> None:
        if self._db is None:
            raise RuntimeError("LocalChunkStore is not open. Call await store.open() first.")

    def __repr__(self) -> str:
        return f"LocalChunkStore(dir={self._dir})"
