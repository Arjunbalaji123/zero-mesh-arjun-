"""
ZeroMesh Node — Complete Integration Layer
============================================
Coordinates:
  - Network: NodeServer listening for inbound peer connections
  - DHT: RoutingTable, KademliaLookup, FindNodeRPC
  - Storage: LocalChunkStore, ManifestRegistry
  - Pipeline: FileManager (chunk, encrypt, distribute, assemble)
  - Peer Reliability: PeerScorer (RTT, uptime, streak)
  - Monitoring: Prometheus metrics collection
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from zeromesh.crypto.engine import generate_key
from zeromesh.dht.kbucket import PeerInfo
from zeromesh.dht.lookup import KademliaLookup
from zeromesh.dht.node_id import NodeID
from zeromesh.dht.routing_table import RoutingTable
from zeromesh.monitoring.metrics import METRICS
from zeromesh.network.connection import PeerAddress, PeerConnection
from zeromesh.network.peer_scorer import PeerScorer
from zeromesh.network.protocol import Message, MessageType
from zeromesh.network.server import NodeServer
from zeromesh.storage.chunk_store import LocalChunkStore
from zeromesh.storage.file_manager import FileManager
from zeromesh.storage.manifest_registry import ManifestRegistry

logger = logging.getLogger(__name__)


class ZeroMeshNode:
    """
    Full ZeroMesh Node instance.
    Runs TCP server, manages DHT routing table, chunk storage,
    and coordinates file uploads/downloads.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7400,
        data_dir: Path | str = "./data",
        key: bytes | None = None,
        node_id: NodeID | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.data_dir = Path(data_dir)
        self.key = key or generate_key()
        self.local_id = node_id or NodeID.from_address(host, port)

        self.routing_table = RoutingTable(self.local_id)
        self.scorer = PeerScorer()
        self.chunk_store = LocalChunkStore(self.data_dir)
        self.manifest_registry = ManifestRegistry(self.data_dir)

        self.file_manager = FileManager(
            local_id=self.local_id,
            routing=self.routing_table,
            store=self.chunk_store,
            registry=self.manifest_registry,
            scorer=self.scorer,
        )

        self.server = NodeServer(
            host=self.host,
            port=self.port,
            handler=self.handle_connection,
        )

        self._refresh_task: asyncio.Task | None = None
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    # ── Connection Handling ───────────────────────────────────────

    async def handle_connection(self, conn: PeerConnection) -> None:
        """Process inbound peer connection RPCs."""
        METRICS.active_connections.inc()
        try:
            while conn.is_open:
                try:
                    msg = await conn.receive(timeout=15.0)
                except asyncio.TimeoutError:
                    break
                except EOFError:
                    break

                METRICS.messages_received_total.inc()
                await self._dispatch_message(conn, msg)
        except Exception as exc:
            logger.debug("Error handling connection from %s: %r", conn.remote_address, exc)
        finally:
            METRICS.active_connections.dec()
            await conn.close()

    async def _dispatch_message(self, conn: PeerConnection, msg: Message) -> None:
        """Route received message to appropriate handler."""
        if msg.type == MessageType.PING:
            sender_id = msg.payload.get("node_id")
            if sender_id and conn.remote_address:
                try:
                    p = PeerInfo(
                        node_id=NodeID.from_hex(sender_id),
                        host=conn.remote_address.host,
                        port=conn.remote_address.port,
                    )
                    self.routing_table.add_peer(p)
                    self.scorer.record_success(sender_id)
                except Exception:
                    pass

            await conn.send(Message.pong(self.local_id.hex))
            METRICS.messages_sent_total.inc()

        elif msg.type == MessageType.PONG:
            sender_id = msg.payload.get("node_id")
            if sender_id:
                self.scorer.record_success(sender_id, rtt_ms=msg.payload.get("rtt_ms"))

        elif msg.type == MessageType.FIND_NODE:
            target_hex = msg.payload.get("target_id")
            sender_hex = msg.payload.get("sender_id")
            if target_hex:
                target = NodeID.from_hex(target_hex)
                closest = self.routing_table.closest_peers(target, count=20)
                nodes = [(p.node_id.hex, p.host, p.port) for p in closest]
                await conn.send(Message.found_nodes(nodes))
                METRICS.messages_sent_total.inc()

            if sender_hex and conn.remote_address:
                try:
                    p = PeerInfo(
                        node_id=NodeID.from_hex(sender_hex),
                        host=conn.remote_address.host,
                        port=conn.remote_address.port,
                    )
                    self.routing_table.add_peer(p)
                except Exception:
                    pass

        elif msg.type == MessageType.STORE_CHUNK:
            content_id = msg.payload["content_id"]
            nonce = msg.payload["nonce"]
            ciphertext = msg.payload["ciphertext"]

            await self.chunk_store.put(content_id, nonce, ciphertext)
            METRICS.chunks_stored_total.inc()
            total_b = await self.chunk_store.total_bytes()
            METRICS.storage_bytes.set(total_b)

            await conn.send(Message.store_ack(content_id))
            METRICS.messages_sent_total.inc()

        elif msg.type == MessageType.GET_CHUNK:
            content_id = msg.payload["content_id"]
            stored = await self.chunk_store.get(content_id)
            if stored is not None:
                nonce, ciphertext = stored
                METRICS.chunks_retrieved_total.inc()
                await conn.send(Message.chunk_data(content_id, nonce, ciphertext))
            else:
                await conn.send(Message.error(404, f"Chunk {content_id} not found"))
            METRICS.messages_sent_total.inc()

        elif msg.type == MessageType.GOODBYE:
            await conn.close()

    # ── Outbound RPC Helpers ──────────────────────────────────────

    async def ping_peer(self, host: str, port: int) -> float | None:
        """
        Send a PING to host:port and measure RTT in milliseconds.
        Returns rtt_ms if peer replied with PONG, else None.
        """
        start_t = time.perf_counter()
        try:
            conn = await asyncio.wait_for(
                PeerConnection.connect(PeerAddress(host, port)),
                timeout=3.0,
            )
            try:
                await conn.send(Message.ping(self.local_id.hex))
                reply = await asyncio.wait_for(conn.receive(), timeout=3.0)
                if reply.type == MessageType.PONG:
                    rtt_ms = (time.perf_counter() - start_t) * 1000.0
                    sender_id = reply.payload.get("node_id")
                    if sender_id:
                        p = PeerInfo(node_id=NodeID.from_hex(sender_id), host=host, port=port)
                        self.routing_table.add_peer(p)
                        self.scorer.record_success(sender_id, rtt_ms=rtt_ms)
                    METRICS.peer_rtt_seconds.observe(rtt_ms / 1000.0)
                    return rtt_ms
            finally:
                await conn.close()
        except Exception as exc:
            logger.debug("Ping to %s:%d failed: %r", host, port, exc)
        return None

    async def find_node_rpc(self, peer: PeerInfo, target: NodeID) -> list[PeerInfo]:
        """
        Kademlia FindNodeRPC implementation over TCP.
        Queries ``peer`` for nodes closest to ``target``.
        """
        try:
            conn = await asyncio.wait_for(
                PeerConnection.connect(PeerAddress(peer.host, peer.port)),
                timeout=4.0,
            )
            try:
                await conn.send(Message.find_node(self.local_id.hex, target.hex))
                reply = await asyncio.wait_for(conn.receive(), timeout=4.0)
                if reply.type == MessageType.FOUND_NODES:
                    raw_nodes = reply.payload.get("nodes", [])
                    results: list[PeerInfo] = []
                    for nid_hex, h, p in raw_nodes:
                        try:
                            results.append(
                                PeerInfo(node_id=NodeID.from_hex(nid_hex), host=h, port=p)
                            )
                        except Exception:
                            continue
                    self.scorer.record_success(peer.node_id.hex)
                    return results
            finally:
                await conn.close()
        except Exception as exc:
            logger.debug("find_node_rpc to %s failed: %r", peer, exc)
            self.scorer.record_failure(peer.node_id.hex)

        return []

    # ── Bootstrap & Peer Discovery ────────────────────────────────

    async def bootstrap(
        self, peers: list[tuple[str, int]] | list[PeerInfo]
    ) -> int:
        """
        Bootstrap into the ZeroMesh network using seed peers.
        Pings seeds, adds responsive peers, then runs iterative lookup
        for local_id to discover neighbourhood.
        """
        logger.info("Bootstrapping via %d candidate peers...", len(peers))
        responsive = 0

        for item in peers:
            if isinstance(item, PeerInfo):
                h, p = item.host, item.port
            else:
                h, p = item

            rtt = await self.ping_peer(h, p)
            if rtt is not None:
                responsive += 1

        if responsive > 0:
            # Iterative lookup for self to populate routing table
            lookup = KademliaLookup(
                local_id=self.local_id,
                target=self.local_id,
                initial_peers=self.routing_table.closest_peers(self.local_id, count=3),
                rpc=self.find_node_rpc,
            )
            discovered = await lookup.run()
            for peer in discovered:
                self.routing_table.add_peer(peer)

        METRICS.active_peers.set(self.routing_table.total_peers)
        logger.info(
            "Bootstrap finished: %d seeds reached, %d peers in routing table",
            responsive,
            self.routing_table.total_peers,
        )
        return responsive

    # ── Background Maintenance ───────────────────────────────────

    async def _periodic_refresh(self, interval_seconds: float = 60.0) -> None:
        """Periodically ping peers and refresh routing table buckets."""
        while self._is_running:
            try:
                await asyncio.sleep(interval_seconds)
                for peer in self.routing_table.all_peers():
                    rtt = await self.ping_peer(peer.host, peer.port)
                    if rtt is None:
                        self.scorer.record_failure(peer.node_id.hex)
                    else:
                        self.scorer.record_success(peer.node_id.hex, rtt_ms=rtt)

                METRICS.active_peers.set(self.routing_table.total_peers)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Error in background peer refresh: %r", exc)

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Start storage engines and TCP server."""
        if self._is_running:
            return

        logger.info(
            "Starting ZeroMesh node %s on %s:%d ...",
            self.local_id.hex[:12],
            self.host,
            self.port,
        )
        await self.chunk_store.open()
        await self.manifest_registry.open()
        await self.server.start()

        self._is_running = True
        self._refresh_task = asyncio.create_task(self._periodic_refresh())
        logger.info("ZeroMesh node running on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        """Gracefully shut down node services."""
        if not self._is_running:
            return

        logger.info("Stopping ZeroMesh node %s ...", self.local_id.hex[:12])
        self._is_running = False

        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass

        await self.server.stop()
        await self.chunk_store.close()
        await self.manifest_registry.close()
        logger.info("ZeroMesh node stopped.")
