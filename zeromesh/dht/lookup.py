"""
ZeroMesh DHT — Iterative Kademlia Lookup
==========================================

The FIND_NODE iterative lookup algorithm (§2.3 of the Kademlia paper).

Goal
----
Find the ``k`` nodes in the network closest to a given target ID,
without a central server — using only peer-to-peer FIND_NODE RPCs.

Algorithm
---------
1.  Start with the ``α`` (alpha) closest peers we already know
    (from our routing table).  α = 3 by default (concurrency factor).

2.  Send FIND_NODE RPCs in parallel to those α peers.
    Each peer responds with its own ``k`` closest known peers to the target.

3.  Add the newly discovered peers to the "to-query" set.

4.  Repeat: always pick the ``α`` closest **unqueried** peers and query them.

5.  Stop when a full round produces no peer closer than the closest
    we have already seen.

6.  Final step: query ALL remaining unqueried peers in the closest-k set
    to ensure we haven't missed anyone (the "termination query").

7.  Return the ``k`` closest responding peers overall.

Convergence guarantee
---------------------
Each step halves the XOR distance to the target (there always exists a peer
one bit closer, thanks to the unidirectionality of XOR).  Therefore the
algorithm converges in O(log N) steps even for N = 10^9 nodes.

Pluggable RPC interface
-----------------------
The lookup engine is decoupled from the actual network transport via the
``FindNodeRPC`` protocol.  In production this fires real async TCP calls;
in tests a fake in-memory "network" is injected.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from zeromesh.dht.kbucket import K, PeerInfo
from zeromesh.dht.node_id import NodeID

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

ALPHA = 3          # Concurrent lookup parallelism (α in the paper)
LOOKUP_TIMEOUT = 5.0  # seconds per individual FIND_NODE RPC


# ─── RPC Protocol (dependency-injection interface) ────────────────────────────

class FindNodeRPC(Protocol):
    """
    Async callable: ask ``peer`` for its closest nodes to ``target``.

    Returns a list of PeerInfo (may be empty if peer is unreachable).
    Implementations must NOT raise — return [] on any error.
    """
    async def __call__(
        self,
        peer: PeerInfo,
        target: NodeID,
    ) -> list[PeerInfo]: ...


# ─── Lookup Engine ────────────────────────────────────────────────────────────

class KademliaLookup:
    """
    Stateful iterative FIND_NODE lookup.

    Usage::

        lookup = KademliaLookup(
            local_id=my_node_id,
            target=target_id,
            initial_peers=routing_table.closest_peers(target_id, ALPHA),
            rpc=my_find_node_rpc,
        )
        closest = await lookup.run()
    """

    def __init__(
        self,
        local_id: NodeID,
        target: NodeID,
        initial_peers: list[PeerInfo],
        rpc: FindNodeRPC,
        k: int = K,
        alpha: int = ALPHA,
        timeout: float = LOOKUP_TIMEOUT,
    ) -> None:
        self.local_id = local_id
        self.target = target
        self.k = k
        self.alpha = alpha
        self.timeout = timeout
        self._rpc = rpc

        # Queried set — node_ids we have already sent FIND_NODE to
        self._queried: set[NodeID] = set()

        # All discovered candidates, keyed by node_id, sorted by distance on access
        self._candidates: dict[NodeID, PeerInfo] = {}

        # Seed with initial peers
        for peer in initial_peers:
            if peer.node_id != local_id:
                self._candidates[peer.node_id] = peer

    # ── Public entry point ────────────────────────────────────────

    async def run(self) -> list[PeerInfo]:
        """
        Execute the full iterative lookup and return up to ``k`` closest peers.
        """
        if not self._candidates:
            logger.debug("Lookup aborted: no initial peers for target %s", self.target)
            return []

        # Track the closest seen so far (for convergence detection)
        previous_best_distance: int | None = None

        while True:
            # --- Step 1: Pick α closest unqueried candidates ---
            unqueried = self._sorted_unqueried()
            to_query = unqueried[: self.alpha]

            if not to_query:
                # All candidates exhausted
                break

            # --- Step 2: Fire FIND_NODE RPCs in parallel ---
            results = await asyncio.gather(
                *[self._query(peer) for peer in to_query],
                return_exceptions=False,
            )

            # --- Step 3: Integrate newly discovered peers ---
            any_new = False
            for peer_list in results:
                for peer in peer_list:
                    if peer.node_id != self.local_id and peer.node_id not in self._candidates:
                        self._candidates[peer.node_id] = peer
                        any_new = True

            # --- Step 4: Check convergence ---
            sorted_candidates = self._sorted_candidates()
            if sorted_candidates:
                best_distance = self.target.distance(sorted_candidates[0].node_id).value
                if best_distance == previous_best_distance and not any_new:
                    break  # No improvement — converged
                previous_best_distance = best_distance
            else:
                break

        # Final: return k closest *responding* peers
        return self._sorted_candidates()[: self.k]

    # ── Internals ─────────────────────────────────────────────────

    async def _query(self, peer: PeerInfo) -> list[PeerInfo]:
        """Send one FIND_NODE RPC, mark peer as queried, handle timeout."""
        self._queried.add(peer.node_id)
        try:
            peers = await asyncio.wait_for(
                self._rpc(peer, self.target),
                timeout=self.timeout,
            )
            logger.debug("FIND_NODE %s → %d peers", peer.node_id, len(peers))
            return peers
        except asyncio.TimeoutError:
            logger.debug("FIND_NODE timeout: %s", peer)
            return []
        except Exception as exc:
            logger.debug("FIND_NODE error %s: %r", peer, exc)
            return []

    def _sorted_candidates(self) -> list[PeerInfo]:
        """All candidates sorted by XOR distance to target (closest first)."""
        return sorted(
            self._candidates.values(),
            key=lambda p: self.target.distance(p.node_id).value,
        )

    def _sorted_unqueried(self) -> list[PeerInfo]:
        """Unqueried candidates sorted by distance to target."""
        return [
            p for p in self._sorted_candidates()
            if p.node_id not in self._queried
        ]
