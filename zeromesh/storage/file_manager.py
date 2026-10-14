"""
ZeroMesh — Distributed File Pipeline
======================================
Connects all subsystems into two high-level operations:

  upload_file(path, key) → manifest_id
    1. Chunk the file (FileChunker)
    2. Encrypt each chunk (AES-256-GCM)
    3. Store locally  (LocalChunkStore)
    4. Publish to DHT peers in parallel (STORE_CHUNK RPC)
    5. Save manifest (ManifestRegistry)

  download_file(manifest_id, key, out_path)
    1. Load manifest (ManifestRegistry)
    2. For each chunk: check local store first (cache hit)
    3. Missing chunks → parallel DHT lookup + GET_CHUNK RPC
    4. Verify SHA-256, decrypt, assemble file (FileAssembler)

This module is the "glue" layer — it orchestrates without containing
business logic itself.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from zeromesh.core.chunker import FileAssembler, FileChunker
from zeromesh.crypto.engine import EncryptedChunk, decrypt_chunk, encrypt_chunk
from zeromesh.dht.kbucket import PeerInfo
from zeromesh.dht.lookup import FindNodeRPC, KademliaLookup
from zeromesh.dht.node_id import NodeID
from zeromesh.dht.routing_table import RoutingTable
from zeromesh.network.connection import PeerAddress, PeerConnection
from zeromesh.network.peer_scorer import PeerScorer
from zeromesh.network.protocol import Message, MessageType
from zeromesh.storage.chunk_store import LocalChunkStore
from zeromesh.storage.manifest_registry import ManifestRegistry

logger = logging.getLogger(__name__)

REPLICATION_FACTOR = 3   # Store each chunk on this many peers


class FileManager:
    """
    High-level file upload / download manager.

    Args:
        local_id:  This node's NodeID.
        routing:   The live routing table (populated as peers join).
        store:     Local chunk store (already opened).
        registry:  Manifest registry (already opened).
        scorer:    Peer reliability scorer.
        chunk_size: Bytes per chunk (default 256 KB).
    """

    def __init__(
        self,
        local_id: NodeID,
        routing: RoutingTable,
        store: LocalChunkStore,
        registry: ManifestRegistry,
        scorer: PeerScorer,
        chunk_size: int = 256 * 1024,
        replication_manager: Any = None,
    ) -> None:
        self._local_id = local_id
        self._routing = routing
        self._store = store
        self._registry = registry
        self._scorer = scorer
        self._replication_manager = replication_manager
        self._chunker = FileChunker(chunk_size=chunk_size)

    async def upload_file(
        self, path: Path, key: bytes, filename: str | None = None
    ) -> str:
        """
        Chunk, encrypt, store locally, and publish chunks to the DHT.

        Returns:
            manifest_id — the SHA-256 fingerprint of the entire file.
        """
        path = Path(path)
        logger.info("Uploading %s ...", filename or path.name)

        # 1. Chunk
        manifest, raw_chunks = self._chunker.chunk_file(path, filename=filename)

        # 2. Encrypt + store locally in parallel (offload crypto to thread)
        enc_chunks: list[EncryptedChunk] = []
        for raw in raw_chunks:
            enc = await asyncio.to_thread(encrypt_chunk, raw, key)
            await self._store.put(enc.content_id, enc.nonce, enc.ciphertext)
            enc_chunks.append(enc)

        # 3. Publish to DHT peers in parallel (fire-and-forget replication)
        all_peers_map = {p.node_id.hex: p for p in self._routing.all_peers()}
        ranked_ids = self._scorer.rank_peers(list(all_peers_map.keys()))
        target_peers = [all_peers_map[nid] for nid in ranked_ids[:REPLICATION_FACTOR]]
        await asyncio.gather(
            *[self._publish_chunk(enc, target_peers) for enc in enc_chunks],
            return_exceptions=True,
        )

        # 4. Save manifest
        await self._registry.save(manifest)
        logger.info(
            "Upload complete: %s → manifest %s (%d chunks)",
            path.name, manifest.manifest_id[:16], manifest.num_chunks
        )
        return manifest.manifest_id

    async def _publish_chunk(
        self, enc: EncryptedChunk, peers: list[PeerInfo]
    ) -> None:
        """Send STORE_CHUNK to a list of peers (best-effort)."""
        msg = Message.store_chunk(enc.content_id, enc.nonce, enc.ciphertext)
        for peer in peers:
            try:
                conn = await asyncio.wait_for(
                    PeerConnection.connect(PeerAddress(peer.host, peer.port)),
                    timeout=3.0,
                )
                await conn.send(msg)
                ack = await conn.receive(timeout=5.0)
                if ack.type == MessageType.STORE_ACK:
                    self._scorer.record_success(peer.node_id.hex, rtt_ms=None)
                    if self._replication_manager is not None:
                        self._replication_manager.track_replica(enc.content_id, peer.node_id.hex)
                await conn.close()
            except Exception as exc:
                logger.debug("Could not replicate chunk to %s: %r", peer, exc)
                self._scorer.record_failure(peer.node_id.hex)

    # ── Download ──────────────────────────────────────────────────

    async def download_file(
        self,
        manifest_id: str,
        key: bytes,
        out_path: Path,
        find_node_rpc: FindNodeRPC | None = None,
    ) -> None:
        """
        Retrieve a file by manifest_id, decrypt, and write to out_path.

        Chunks are fetched in parallel (from local cache or remote peers).
        Each chunk is SHA-256 verified before decryption.
        """
        manifest = await self._registry.get(manifest_id)
        if manifest is None:
            raise FileNotFoundError(f"Manifest {manifest_id[:16]}... not found locally")

        logger.info(
            "Downloading %s (%d chunks) ...", manifest.filename, manifest.num_chunks
        )

        assembler = FileAssembler(manifest)

        # Fetch all chunks concurrently
        results = await asyncio.gather(
            *[
                self._fetch_chunk(meta.content_id, meta.index, key, find_node_rpc)
                for meta in manifest.chunks
            ],
            return_exceptions=True,
        )

        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                raise RuntimeError(
                    f"Failed to retrieve chunk {i}: {result}"
                ) from result
            assembler.add_chunk(i, result)

        assembler.write_to(out_path)
        logger.info("Download complete → %s", out_path)

    async def _fetch_chunk(
        self,
        content_id: str,
        index: int,
        key: bytes,
        find_node_rpc: FindNodeRPC | None,
    ) -> bytes:
        """
        Fetch one chunk: try local cache first, then peer network.
        Returns decrypted plaintext bytes.
        """
        # Local cache hit
        cached = await self._store.get(content_id)
        if cached is not None:
            nonce, ciphertext = cached
            enc = EncryptedChunk(nonce=nonce, ciphertext=ciphertext, content_id=content_id)
            return decrypt_chunk(enc, key)

        # DHT lookup for peers holding this chunk
        target_node_id = NodeID.from_content_id(content_id)
        initial = self._routing.closest_peers(target_node_id, count=3)

        if find_node_rpc is not None:
            lookup = KademliaLookup(
                local_id=self._local_id,
                target=target_node_id,
                initial_peers=initial,
                rpc=find_node_rpc,
            )
            candidate_peers = await lookup.run()
        else:
            candidate_peers = initial

        # Try peers in reliability order
        ranked = self._scorer.rank_peers([p.node_id.hex for p in candidate_peers])
        peer_map = {p.node_id.hex: p for p in candidate_peers}

        for peer_hex in ranked:
            peer = peer_map.get(peer_hex)
            if peer is None:
                continue
            try:
                nonce, ciphertext = await self._get_chunk_from_peer(peer, content_id)
                enc = EncryptedChunk(
                    nonce=nonce, ciphertext=ciphertext, content_id=content_id
                )
                # Verify and decrypt offloaded to worker thread (no event loop blocking)
                plaintext = await asyncio.to_thread(decrypt_chunk, enc, key)

                # Cache locally upon verified decryption
                await self._store.put(content_id, nonce, ciphertext)
                self._scorer.record_success(peer_hex)
                return plaintext
            except (ValueError, Exception) as exc:
                # Check if it was an integrity or tampering failure
                from cryptography.exceptions import InvalidTag
                if isinstance(exc, (InvalidTag, ValueError)) and "mismatch" in str(exc).lower():
                    logger.warning("INTEGRITY FAILURE: Peer %s sent corrupted chunk %s: %r", peer, content_id[:8], exc)
                    self._scorer.record_integrity_failure(peer_hex)
                else:
                    logger.debug("Peer %s failed for chunk %s: %r", peer, content_id[:8], exc)
                    self._scorer.record_failure(peer_hex)

        raise RuntimeError(f"Could not retrieve chunk {content_id[:16]}... from any peer")

    async def _get_chunk_from_peer(
        self, peer: PeerInfo, content_id: str
    ) -> tuple[bytes, bytes]:
        """Send GET_CHUNK RPC and return (nonce, ciphertext)."""
        conn = await asyncio.wait_for(
            PeerConnection.connect(PeerAddress(peer.host, peer.port)),
            timeout=5.0,
        )
        try:
            await conn.send(Message.get_chunk(content_id))
            reply = await conn.receive(timeout=10.0)
            if reply.type != MessageType.CHUNK_DATA:
                raise ValueError(f"Expected CHUNK_DATA, got {reply.type.name}")
            return reply.payload["nonce"], reply.payload["ciphertext"]
        finally:
            await conn.close()
