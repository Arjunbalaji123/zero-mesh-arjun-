import hashlib
import uuid
from typing import List, Tuple
from app.config import CHUNK_SIZE_BYTES
from app.models.schemas import ChunkMetadata, FileMetadata


def calculate_sha256(data: bytes) -> str:
    """Computes standard hex SHA-256 hash of bytes."""
    return hashlib.sha256(data).hexdigest()


def chunk_file(
    file_data: bytes,
    filename: str,
    file_id: str = None,
    chunk_size: int = CHUNK_SIZE_BYTES,
) -> Tuple[FileMetadata, List[Tuple[ChunkMetadata, bytes]]]:
    """
    Splits binary file data into chunks of `chunk_size` bytes.
    Returns FileMetadata and a list of (ChunkMetadata, chunk_bytes).
    """
    if not file_id:
        file_id = str(uuid.uuid4())

    file_hash = calculate_sha256(file_data)
    file_size = len(file_data)
    chunks_with_data: List[Tuple[ChunkMetadata, bytes]] = []
    chunk_metas: List[ChunkMetadata] = []

    seq = 0
    offset = 0

    if file_size == 0:
        # Handle empty file case
        c_hash = calculate_sha256(b"")
        c_id = calculate_sha256(f"{file_id}_{seq}_{c_hash}".encode())
        meta = ChunkMetadata(
            chunk_id=c_id,
            file_id=file_id,
            sequence_number=0,
            sha256_hash=c_hash,
            size=0,
        )
        chunk_metas.append(meta)
        chunks_with_data.append((meta, b""))
    else:
        while offset < file_size:
            chunk_bytes = file_data[offset : offset + chunk_size]
            c_hash = calculate_sha256(chunk_bytes)
            # Unique deterministic/identifiable chunk_id from file_id + sequence + content hash
            c_id = calculate_sha256(f"{file_id}_{seq}_{c_hash}".encode())

            meta = ChunkMetadata(
                chunk_id=c_id,
                file_id=file_id,
                sequence_number=seq,
                sha256_hash=c_hash,
                size=len(chunk_bytes),
            )
            chunk_metas.append(meta)
            chunks_with_data.append((meta, chunk_bytes))

            seq += 1
            offset += chunk_size

    file_meta = FileMetadata(
        file_id=file_id,
        filename=filename,
        file_size=file_size,
        chunk_count=len(chunk_metas),
        chunk_size=chunk_size,
        file_hash=file_hash,
        chunks=chunk_metas,
    )

    return file_meta, chunks_with_data


def reassemble_chunks(chunks_with_data: List[Tuple[ChunkMetadata, bytes]]) -> bytes:
    """
    Sorts chunks by sequence_number, verifies sha256 of each chunk, and reassembles original file bytes.
    Raises ValueError on integrity hash mismatch.
    """
    sorted_chunks = sorted(chunks_with_data, key=lambda x: x[0].sequence_number)
    reassembled_bytes = bytearray()

    for meta, chunk_bytes in sorted_chunks:
        actual_hash = calculate_sha256(chunk_bytes)
        if actual_hash != meta.sha256_hash:
            raise ValueError(
                f"Integrity check failed for chunk {meta.chunk_id} seq {meta.sequence_number}. "
                f"Expected {meta.sha256_hash}, got {actual_hash}"
            )
        reassembled_bytes.extend(chunk_bytes)

    return bytes(reassembled_bytes)
