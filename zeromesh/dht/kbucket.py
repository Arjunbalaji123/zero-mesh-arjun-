"""
ZeroMesh DHT — K-Bucket
========================

A K-Bucket holds up to ``k`` (default 20) peers that are all at the same
logarithmic XOR distance from the local node.

Replacement policy (from the Kademlia paper §2.2)
--------------------------------------------------
When a bucket is full and a new peer is discovered:

  1. Ping the **least-recently-seen** (LRS) peer in the bucket.
  2. If the LRS peer responds → move it to the tail (most-recently-seen)
     and DISCARD the new peer.
  3. If the LRS peer does NOT respond → evict it and INSERT the new peer.

Rationale: long-lived peers are far more likely to stay online.
This "prefer old nodes" policy dramatically improves DHT stability
under churn.

Implementation note
-------------------
We store peers in a ``deque`` ordered from LRS (left) to MRS (right).
When a peer is seen (send or receive), it is moved to the right end.
The LRS candidate for eviction is always ``bucket[0]``.

We also maintain a bounded ``replacement_cache`` (deque) for peers that
arrived when the bucket was full. If the LRS peer is evicted, the most
recently seen peer from the cache takes its slot.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from zeromesh.dht.node_id import NodeID


# ─── Constants ────────────────────────────────────────────────────────────────

K = 20                      # Kademlia k-parameter: max peers per bucket
REPLACEMENT_CACHE_SIZE = 5  # How many pending peers to keep when bucket is full


# ─── Peer Entry ───────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class PeerInfo:
    """
    The minimum information needed to contact a peer.

    Attributes:
        node_id: The peer's 256-bit Kademlia ID.
        host:    IP address or hostname.
        port:    TCP port number.
    """
    node_id: NodeID
    host: str
    port: int

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PeerInfo):
            return self.node_id == other.node_id
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.node_id)

    def __repr__(self) -> str:
        return f"PeerInfo({self.node_id!r}, {self.host}:{self.port})"


# ─── K-Bucket ─────────────────────────────────────────────────────────────────

class KBucket:
    """
    Holds up to ``k`` PeerInfo entries at the same logarithmic distance band.

    Internal invariant:
        ``peers[0]`` is the Least-Recently-Seen peer.
        ``peers[-1]`` is the Most-Recently-Seen peer.
    """

    def __init__(self, k: int = K) -> None:
        self.k = k
        self._peers: deque[PeerInfo] = deque()
        self._peer_ids: set[NodeID] = set()
        self._replacement_cache: deque[PeerInfo] = deque(maxlen=REPLACEMENT_CACHE_SIZE)

    # ── Peer management ───────────────────────────────────────────

    def add_or_update(self, peer: PeerInfo) -> bool:
        """
        Insert a newly seen peer or move it to MRS position.

        Returns:
            True  — peer was inserted or updated successfully.
            False — bucket is full; caller should ping LRS peer to decide eviction.
        """
        if peer.node_id in self._peer_ids:
            # Already known — move to MRS (right end)
            self._peers.remove(peer)
            self._peers.append(peer)
            return True

        if len(self._peers) < self.k:
            self._peers.append(peer)
            self._peer_ids.add(peer.node_id)
            return True

        # Bucket full — add to replacement cache, caller handles LRS ping
        if peer not in self._replacement_cache:
            self._replacement_cache.append(peer)
        return False

    def mark_seen(self, node_id: NodeID) -> None:
        """Move a peer to MRS position (called on any successful contact)."""
        for peer in self._peers:
            if peer.node_id == node_id:
                self._peers.remove(peer)
                self._peers.append(peer)
                return

    def evict_lrs_and_promote(self) -> PeerInfo | None:
        """
        Remove the LRS (least-recently-seen) peer and promote the most
        recent replacement cache entry in its place.

        Returns the evicted PeerInfo (caller should mark it as dead),
        or None if the bucket is empty.
        """
        if not self._peers:
            return None

        evicted = self._peers.popleft()
        self._peer_ids.discard(evicted.node_id)

        # Promote from replacement cache
        if self._replacement_cache:
            promoted = self._replacement_cache.pop()  # most recently queued
            self._peers.append(promoted)
            self._peer_ids.add(promoted.node_id)

        return evicted

    def remove(self, node_id: NodeID) -> bool:
        """
        Forcibly remove a peer (e.g., confirmed dead via health check).

        Returns True if removed, False if not found.
        """
        for peer in list(self._peers):
            if peer.node_id == node_id:
                self._peers.remove(peer)
                self._peer_ids.discard(node_id)
                # Promote from cache
                if self._replacement_cache:
                    promoted = self._replacement_cache.pop()
                    self._peers.append(promoted)
                    self._peer_ids.add(promoted.node_id)
                return True
        return False

    # ── Queries ───────────────────────────────────────────────────

    def contains(self, node_id: NodeID) -> bool:
        return node_id in self._peer_ids

    @property
    def lrs(self) -> PeerInfo | None:
        """Least-Recently-Seen peer (eviction candidate)."""
        return self._peers[0] if self._peers else None

    @property
    def mrs(self) -> PeerInfo | None:
        """Most-Recently-Seen peer."""
        return self._peers[-1] if self._peers else None

    @property
    def peers(self) -> list[PeerInfo]:
        """Snapshot of all peers, LRS first."""
        return list(self._peers)

    @property
    def is_full(self) -> bool:
        return len(self._peers) >= self.k

    def __len__(self) -> int:
        return len(self._peers)

    def __repr__(self) -> str:
        return f"KBucket(size={len(self)}/{self.k})"
