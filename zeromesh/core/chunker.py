"""
ZeroMesh Core — File Chunker
=============================
Splits files into fixed-size chunks, tracks metadata,
and reassembles them after retrieval.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from zeromesh.crypto.engine import sha256_hash

# ─── Constants ────────────────────────────────────────────────────────────────

DEFAULT_CHUNK_SIZE = 256 * 1024  # 256 KB per chunk


# ─── Data Structures ──────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ChunkMeta:
    """
    Metadata for a single file chunk.

    Attributes:
        index:       Zero-based position of this chunk in the file.
        content_id:  SHA-256 hex digest of the raw plaintext bytes.
                     Used as the DHT key for content-addressed storage.
        size:        Number of bytes in this chunk.
    """
    index: int
    content_id: str
    size: int


@dataclass
class FileManifest:
    """
    Complete manifest describing a chunked file.

    After uploading, this manifest is what peers need to reconstruct the file.
    It is itself content-addressed (manifest_id = SHA-256 of its canonical form).

    Attributes:
        filename:    Original filename (basename only).
        total_size:  Total file size in bytes.
        chunk_size:  The fixed chunk size used (last chunk may be smaller).
        chunks:      Ordered list of ChunkMeta — order matters for reassembly.
        manifest_id: SHA-256 of the joined content IDs (fingerprint of the whole file).
    """
    filename: str
    total_size: int
    chunk_size: int
    chunks: list[ChunkMeta] = field(default_factory=list)
    manifest_id: str = field(init=False)

    def __post_init__(self) -> None:
        self.manifest_id = self._compute_manifest_id()

    def _compute_manifest_id(self) -> str:
        """
        Stable fingerprint: SHA-256 over the concatenation of all chunk content IDs
        in index order. This uniquely identifies the exact file content.
        """
        joined = "".join(c.content_id for c in self.chunks)
        return sha256_hash(joined.encode())

    @property
    def num_chunks(self) -> int:
        return len(self.chunks)

    def __repr__(self) -> str:
        return (
            f"FileManifest({self.filename!r}, "
            f"total={self.total_size}B, "
            f"chunks={self.num_chunks}, "
            f"id={self.manifest_id[:16]}...)"
        )


# ─── Chunker ──────────────────────────────────────────────────────────────────

class FileChunker:
    """
    Splits a file into fixed-size plaintext chunks and produces a FileManifest.

    Usage::

        chunker = FileChunker(chunk_size=256 * 1024)
        manifest, chunks = chunker.chunk_file(Path("myfile.txt"))
        # chunks: list[bytes]  — raw plaintext bytes for each chunk
        # manifest: FileManifest — metadata needed for reassembly
    """

    def __init__(self, chunk_size: int = DEFAULT_CHUNK_SIZE) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be a positive integer")
        self.chunk_size = chunk_size

    def chunk_file(
        self, path: Path, filename: str | None = None
    ) -> tuple[FileManifest, list[bytes]]:
        """
        Read a file from disk, split it into chunks, compute SHA-256 per chunk.

        Args:
            path: Path to the file to chunk.
            filename: Optional custom filename to record in manifest (default path.name).

        Returns:
            (FileManifest, list_of_chunk_bytes) — the manifest and raw chunks.

        Raises:
            FileNotFoundError: if ``path`` does not exist.
            IsADirectoryError: if ``path`` is a directory.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if path.is_dir():
            raise IsADirectoryError(f"Expected a file, got a directory: {path}")

        total_size = path.stat().st_size
        raw_chunks: list[bytes] = list(self._read_chunks(path))

        chunk_metas = [
            ChunkMeta(
                index=i,
                content_id=sha256_hash(chunk),
                size=len(chunk),
            )
            for i, chunk in enumerate(raw_chunks)
        ]

        manifest = FileManifest(
            filename=filename or path.name,
            total_size=total_size,
            chunk_size=self.chunk_size,
            chunks=chunk_metas,
        )

        return manifest, raw_chunks

    def _read_chunks(self, path: Path) -> Iterator[bytes]:
        """Lazily read the file in ``chunk_size`` byte windows."""
        with path.open("rb") as fh:
            while True:
                data = fh.read(self.chunk_size)
                if not data:
                    break
                yield data

    @staticmethod
    def expected_chunks(file_size: int, chunk_size: int) -> int:
        """Return the expected number of chunks for a given file size."""
        return math.ceil(file_size / chunk_size) if file_size > 0 else 0


# ─── Assembler ────────────────────────────────────────────────────────────────

class FileAssembler:
    """
    Reassembles decrypted plaintext chunks back into the original file.

    Usage::

        assembler = FileAssembler(manifest)
        assembler.add_chunk(index=0, data=chunk0_plaintext)
        assembler.add_chunk(index=1, data=chunk1_plaintext)
        # ... add all chunks, optionally out of order
        assembler.write_to(Path("recovered.txt"))
    """

    def __init__(self, manifest: FileManifest) -> None:
        self.manifest = manifest
        self._chunks: dict[int, bytes] = {}

    def add_chunk(self, index: int, data: bytes) -> None:
        """
        Add a decrypted, integrity-verified chunk.

        Args:
            index: Zero-based chunk index.
            data:  Raw plaintext bytes of this chunk.

        Raises:
            ValueError: if the SHA-256 of ``data`` doesn't match the manifest.
        """
        expected_cid = self.manifest.chunks[index].content_id
        actual_cid = sha256_hash(data)
        if actual_cid != expected_cid:
            raise ValueError(
                f"Chunk {index} integrity failure: "
                f"expected {expected_cid[:16]}..., got {actual_cid[:16]}..."
            )
        self._chunks[index] = data

    @property
    def is_complete(self) -> bool:
        """True when all chunks have been received."""
        return len(self._chunks) == self.manifest.num_chunks

    @property
    def missing_indices(self) -> list[int]:
        """Return sorted list of chunk indices not yet received."""
        all_indices = set(range(self.manifest.num_chunks))
        return sorted(all_indices - set(self._chunks))

    def write_to(self, output_path: Path) -> None:
        """
        Write the reassembled file to ``output_path``.

        Raises:
            RuntimeError: if not all chunks have been received.
        """
        if not self.is_complete:
            raise RuntimeError(
                f"Cannot assemble: missing chunks {self.missing_indices}"
            )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("wb") as fh:
            for i in range(self.manifest.num_chunks):
                fh.write(self._chunks[i])
