"""
ZeroMesh Replication & Repair Manager
=====================================
Manages:
  - Trust-aware replica placement across the closest and most reliable peers.
  - Background repair loop detecting under-replicated chunks during churn or peer departures.
  - Periodic challenge-response chunk health audits: asks a peer to prove possession
    by computing SHA-256(chunk_bytes || challenge_nonce).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING

from zeromesh.crypto.engine import sha256_hash
from zeromesh.dht.kbucket import PeerInfo
from zeromesh.dht.node_id import NodeID
from zeromesh.network.connection import PeerAddress, PeerConnection
from zeromesh.network.protocol import Message, MessageType

if TYPE_CHECKING:
    from zeromesh.dht.routing_table import RoutingTable
    from zeromesh.network.peer_scorer import PeerScorer
    from zeromesh.storage.chunk_store import LocalChunkStore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReplicationConfig:
    replication_factor: int = 3
    audit_interval_seconds: float = 60.0
    repair_interval_seconds: float = 30.0
    challenge_timeout_seconds: float = 4.0


class ReplicationManager:
    """
    Coordinates replica tracking, challenge-response health audits, and active repair.
    """

    def __init__(
        self,
        local_id: NodeID,
        routing_table: RoutingTable,
        chunk_store: LocalChunkStore,
        scorer: PeerScorer,
        config: ReplicationConfig | None = None,
    ) -> None:
        self.local_id = local_id
        self.routing = routing_table
        self.store = chunk_store
        self.scorer = scorer
        self.config = config or ReplicationConfig()

        # Track chunk replica locations: content_id -> set of peer node_id hex strings
        self._replicas: dict[str, set[str]] = {}
        self._repair_task: asyncio.Task[None] | None = None
        self._is_running = False

    def track_replica(self, content_id: str, peer_id_hex: str) -> None:
        """Register that a remote peer holds a copy of content_id."""
        if content_id not in self._replicas:
            self._replicas[content_id] = set()
        self._replicas[content_id].add(peer_id_hex)

    def select_placement_peers(self, content_id: str, count: int | None = None) -> list[PeerInfo]:
        """
        Select the best peers for replica placement:
        Combines DHT proximity (closest to content_id) with trust score ranking.
        Excludes blacklisted peers.
        """
        k = count or self.config.replication_factor
        target = NodeID.from_content_id(content_id)
        candidate_peers = self.routing.closest_peers(target, count=k * 2)

        # Filter out blacklisted peers
        healthy_candidates = [
            p for p in candidate_peers if not self.scorer.is_blacklisted(p.node_id.hex)
        ]

        # Rank by trust score
        ranked_hex = self.scorer.rank_peers([p.node_id.hex for p in healthy_candidates])
        peer_by_hex = {p.node_id.hex: p for p in healthy_candidates}
        return [peer_by_hex[h] for h in ranked_hex[:k] if h in peer_by_hex]

    async def audit_peer_chunk(self, peer: PeerInfo, content_id: str) -> bool:
        """
        Execute challenge-response audit:
        Send random nonce; peer must reply with sha256(chunk_bytes || nonce).
        """
        local_chunk = await self.store.get(content_id)
        if local_chunk is None:
            return False

        nonce, ciphertext = local_chunk
        challenge_nonce = secrets.token_bytes(16)
        expected_proof = sha256_hash(nonce + ciphertext + challenge_nonce)

        try:
            conn = await asyncio.wait_for(
                PeerConnection.connect(PeerAddress(peer.host, peer.port)),
                timeout=self.config.challenge_timeout_seconds,
            )
            try:
                await conn.send(Message.audit_challenge(content_id, challenge_nonce))
                reply = await asyncio.wait_for(
                    conn.receive(), timeout=self.config.challenge_timeout_seconds
                )
                if reply.type == MessageType.AUDIT_RESPONSE:
                    proof = reply.payload.get("proof")
                    if proof == expected_proof:
                        self.scorer.record_success(peer.node_id.hex)
                        return True
                    else:
                        logger.warning(
                            "Audit failed! Peer %s failed challenge for %s",
                            peer.node_id.hex[:8],
                            content_id[:8],
                        )
                        self.scorer.record_integrity_failure(peer.node_id.hex)
                        return False
            finally:
                await conn.close()
        except Exception as exc:
            logger.debug("Audit connection to %s timed out/failed: %r", peer, exc)
            self.scorer.record_failure(peer.node_id.hex)
            return False

        return False

    async def check_and_repair(self) -> int:
        """
        Inspect all tracked chunks. If the number of reachable, valid replicas
        falls below replication_factor, replicate to additional closest/trusted peers.
        Returns the number of chunks repaired.
        """
        all_peers_map = {p.node_id.hex: p for p in self.routing.all_peers()}
        repaired_count = 0

        for content_id, holding_peers in list(self._replicas.items()):
            # Count how many holding peers are still active and responsive
            alive_replicas = 0
            for peer_hex in list(holding_peers):
                peer = all_peers_map.get(peer_hex)
                if peer is None or self.scorer.is_blacklisted(peer_hex):
                    holding_peers.discard(peer_hex)
                else:
                    alive_replicas += 1

            # Need repair?
            deficit = self.config.replication_factor - alive_replicas
            if deficit > 0:
                chunk = await self.store.get(content_id)
                if chunk is not None:
                    nonce, ciphertext = chunk
                    target_peers = self.select_placement_peers(content_id, count=deficit + len(holding_peers))
                    # Exclude already holding peers
                    new_targets = [p for p in target_peers if p.node_id.hex not in holding_peers][:deficit]

                    msg = Message.store_chunk(content_id, nonce, ciphertext)
                    for target in new_targets:
                        try:
                            conn = await asyncio.wait_for(
                                PeerConnection.connect(PeerAddress(target.host, target.port)),
                                timeout=3.0,
                            )
                            await conn.send(msg)
                            ack = await conn.receive(timeout=3.0)
                            if ack.type == MessageType.STORE_ACK:
                                self.track_replica(content_id, target.node_id.hex)
                                self.scorer.record_success(target.node_id.hex)
                                repaired_count += 1
                            await conn.close()
                        except Exception as exc:
                            logger.debug("Failed re-replicating to %s: %r", target, exc)

        return repaired_count

    async def start(self) -> None:
        """Start the background repair and health audit loop."""
        if self._is_running:
            return
        self._is_running = True
        self._repair_task = asyncio.create_task(self._repair_loop())

    async def stop(self) -> None:
        """Stop background tasks."""
        self._is_running = False
        if self._repair_task and not self._repair_task.done():
            self._repair_task.cancel()
            try:
                await self._repair_task
            except asyncio.CancelledError:
                pass

    async def _repair_loop(self) -> None:
        while self._is_running:
            try:
                await asyncio.sleep(self.config.repair_interval_seconds)
                await self.check_and_repair()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Error in background replication repair: %r", exc)

