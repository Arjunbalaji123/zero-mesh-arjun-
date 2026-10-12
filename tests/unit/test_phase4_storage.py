"""
Unit tests — Phase 4: Storage Engine & Distributed File Pipeline
  - LocalChunkStore (disk persistence, 2-char prefix sharding, SQLite index)
  - ManifestRegistry (CRUD operations, JSON serialization)
  - FileManager (upload chunking/encryption, download decryption/assembly)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from zeromesh.core.chunker import ChunkMeta, FileManifest
from zeromesh.crypto.engine import generate_key
from zeromesh.dht.node_id import NodeID
from zeromesh.dht.routing_table import RoutingTable
from zeromesh.network.peer_scorer import PeerScorer
from zeromesh.storage.chunk_store import LocalChunkStore
from zeromesh.storage.manifest_registry import ManifestRegistry
from zeromesh.storage.file_manager import FileManager


# ─── LocalChunkStore Tests ───────────────────────────────────────────────────

class TestLocalChunkStore:
    @pytest.mark.asyncio
    async def test_put_and_get(self, tmp_path: Path):
        store = LocalChunkStore(tmp_path)
        await store.open()

        content_id = "a1b2c3d4" * 8
        nonce = os.urandom(12)
        ciphertext = b"encrypted chunk payload test"

        await store.put(content_id, nonce, ciphertext)

        result = await store.get(content_id)
        assert result is not None
        retrieved_nonce, retrieved_ct = result
        assert retrieved_nonce == nonce
        assert retrieved_ct == ciphertext

        assert await store.has(content_id) is True
        assert await store.total_chunks() == 1
        assert await store.total_bytes() == len(ciphertext)

        await store.close()

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, tmp_path: Path):
        store = LocalChunkStore(tmp_path)
        await store.open()

        assert await store.get("nonexistent_content_id") is None
        assert await store.has("nonexistent_content_id") is False

        await store.close()

    @pytest.mark.asyncio
    async def test_sharded_path_structure(self, tmp_path: Path):
        store = LocalChunkStore(tmp_path)
        await store.open()

        content_id = "ff" + "00" * 31
        await store.put(content_id, os.urandom(12), b"payload")

        expected_dir = tmp_path / "chunks" / "ff"
        assert expected_dir.exists()
        assert (expected_dir / f"{content_id}.chunk").exists()

        await store.close()

    @pytest.mark.asyncio
    async def test_delete_chunk(self, tmp_path: Path):
        store = LocalChunkStore(tmp_path)
        await store.open()

        content_id = "12345678" * 8
        await store.put(content_id, os.urandom(12), b"to_delete")
        assert await store.has(content_id) is True

        deleted = await store.delete(content_id)
        assert deleted is True
        assert await store.has(content_id) is False
        assert await store.get(content_id) is None

        # Deleting again returns False
        assert await store.delete(content_id) is False

        await store.close()

    @pytest.mark.asyncio
    async def test_persistence_across_reopen(self, tmp_path: Path):
        store = LocalChunkStore(tmp_path)
        await store.open()
        cid = "aabbccdd" * 8
        nonce = os.urandom(12)
        ct = b"persistent data"
        await store.put(cid, nonce, ct)
        await store.close()

        # Reopen same dir
        store2 = LocalChunkStore(tmp_path)
        await store2.open()
        res = await store2.get(cid)
        assert res == (nonce, ct)
        all_chunks = await store2.list_all()
        assert len(all_chunks) == 1
        assert all_chunks[0].content_id == cid
        await store2.close()


# ─── ManifestRegistry Tests ──────────────────────────────────────────────────

class TestManifestRegistry:
    @pytest.mark.asyncio
    async def test_save_and_get(self, tmp_path: Path):
        registry = ManifestRegistry(tmp_path)
        await registry.open()

        manifest = FileManifest(
            filename="document.pdf",
            total_size=1024,
            chunk_size=512,
            chunks=[
                ChunkMeta(index=0, content_id="cid_0", size=512),
                ChunkMeta(index=1, content_id="cid_1", size=512),
            ],
        )

        await registry.save(manifest)
        retrieved = await registry.get(manifest.manifest_id)
        assert retrieved is not None
        assert retrieved.filename == "document.pdf"
        assert retrieved.total_size == 1024
        assert retrieved.chunk_size == 512
        assert retrieved.num_chunks == 2
        assert retrieved.chunks[0].content_id == "cid_0"
        assert retrieved.chunks[1].content_id == "cid_1"

        await registry.close()

    @pytest.mark.asyncio
    async def test_list_and_delete(self, tmp_path: Path):
        registry = ManifestRegistry(tmp_path)
        await registry.open()

        m1 = FileManifest("a.txt", 10, 10, [ChunkMeta(0, "c1", 10)])
        m2 = FileManifest("b.txt", 20, 10, [ChunkMeta(0, "c2", 10), ChunkMeta(1, "c3", 10)])

        await registry.save(m1)
        await registry.save(m2)

        items = await registry.list_all()
        assert len(items) == 2

        assert await registry.delete(m1.manifest_id) is True
        assert await registry.get(m1.manifest_id) is None
        assert len(await registry.list_all()) == 1

        await registry.close()


# ─── FileManager Pipeline Tests ──────────────────────────────────────────────

class TestFileManager:
    @pytest.mark.asyncio
    async def test_upload_and_download_roundtrip(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        local_id = NodeID.random()
        routing = RoutingTable(local_id)
        store = LocalChunkStore(data_dir)
        registry = ManifestRegistry(data_dir)
        scorer = PeerScorer()

        await store.open()
        await registry.open()

        file_mgr = FileManager(
            local_id=local_id,
            routing=routing,
            store=store,
            registry=registry,
            scorer=scorer,
            chunk_size=1024,
        )

        # Create test file (larger than 1 chunk)
        src_file = tmp_path / "sample.bin"
        original_bytes = os.urandom(3500)
        src_file.write_bytes(original_bytes)

        key = generate_key()

        # 1. Upload
        manifest_id = await file_mgr.upload_file(src_file, key)
        assert isinstance(manifest_id, str)
        assert len(manifest_id) == 64  # SHA-256 hex

        # Check chunks were stored
        manifest = await registry.get(manifest_id)
        assert manifest is not None
        assert manifest.num_chunks == 4  # 3500 bytes / 1024 = 3 chunks of 1024 + 1 chunk of 428

        for chunk_meta in manifest.chunks:
            assert await store.has(chunk_meta.content_id) is True

        # 2. Download to new path
        dst_file = tmp_path / "restored.bin"
        await file_mgr.download_file(manifest_id, key, dst_file)

        assert dst_file.exists()
        restored_bytes = dst_file.read_bytes()
        assert restored_bytes == original_bytes

        await store.close()
        await registry.close()
