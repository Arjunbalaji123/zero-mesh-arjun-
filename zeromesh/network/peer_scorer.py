"""
ZeroMesh Network — Peer Reliability Scorer
===========================================
Tracks each peer's observed behaviour and produces a reliability score (0.0–1.0).

Factors:
  - RTT (lower = better)
  - Success rate of message exchanges
  - Consecutive failure streak (penalises flapping peers)
  - Last-seen recency

A peer's score determines:
  - K-bucket eviction priority (low-score peers evicted first)
  - Chunk retrieval peer selection (prefer high-score peers)
  - Replication target preference
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field


# ─── Constants ────────────────────────────────────────────────────────────────

RTT_IDEAL_MS     = 20.0    # Sub-20 ms → max RTT score
RTT_WORST_MS     = 2000.0  # Above this → zero RTT score
MAX_RTT_SAMPLES  = 50      # Rolling window size for RTT EWMA
DECAY_HALF_LIFE  = 3600.0  # Seconds: recency score halves every hour


# ─── Peer Stats ───────────────────────────────────────────────────────────────

@dataclass
class PeerStats:
    """
    Mutable runtime statistics for a single peer.

    All timestamps are Unix epoch floats (time.monotonic is NOT used here
    because we want wall-clock recency for decay calculations).
    """
    node_id: str

    # Message exchange counters
    total_requests:   int   = 0
    successful:       int   = 0
    failed:           int   = 0
    consecutive_failures: int = 0

    # RTT tracking (Exponentially Weighted Moving Average)
    rtt_ewma_ms:  float = 0.0
    rtt_samples:  int   = 0

    # Timestamps
    first_seen:   float = field(default_factory=time.time)
    last_seen:    float = field(default_factory=time.time)

    # Chunk transfer counters
    chunks_stored:    int = 0
    chunks_retrieved: int = 0

    def record_success(self, rtt_ms: float | None = None) -> None:
        """Record a successful exchange, optionally with an RTT sample."""
        self.total_requests += 1
        self.successful += 1
        self.consecutive_failures = 0
        self.last_seen = time.time()

        if rtt_ms is not None and rtt_ms > 0:
            self._update_rtt(rtt_ms)

    def record_failure(self) -> None:
        """Record a failed / timed-out exchange."""
        self.total_requests += 1
        self.failed += 1
        self.consecutive_failures += 1

    def _update_rtt(self, sample_ms: float) -> None:
        """
        EWMA update: alpha decreases as we collect more samples
        (similar to TCP's smoothed RTT estimator).
        """
        self.rtt_samples += 1
        alpha = 1.0 / min(self.rtt_samples, MAX_RTT_SAMPLES)
        if self.rtt_ewma_ms == 0.0:
            self.rtt_ewma_ms = sample_ms
        else:
            self.rtt_ewma_ms = alpha * sample_ms + (1 - alpha) * self.rtt_ewma_ms

    @property
    def success_rate(self) -> float:
        """Fraction of successful requests, 0.0–1.0. Returns 1.0 if no requests yet."""
        if self.total_requests == 0:
            return 1.0
        return self.successful / self.total_requests


# ─── Scorer ───────────────────────────────────────────────────────────────────

class PeerScorer:
    """
    Computes a composite reliability score for each known peer.

    Score components (each 0.0–1.0, linearly weighted):

        score = 0.40 * rtt_score
              + 0.35 * success_score
              + 0.15 * recency_score
              + 0.10 * streak_score

    The streak score heavily penalises peers with consecutive failures,
    making unreliable peers drop off quickly even if their historical
    success rate is still decent.
    """

    def __init__(self) -> None:
        self._stats: dict[str, PeerStats] = {}

    # ── Stats access ──────────────────────────────────────────────

    def get_or_create(self, node_id: str) -> PeerStats:
        if node_id not in self._stats:
            self._stats[node_id] = PeerStats(node_id=node_id)
        return self._stats[node_id]

    def get(self, node_id: str) -> PeerStats | None:
        return self._stats.get(node_id)

    def record_success(self, node_id: str, rtt_ms: float | None = None) -> None:
        self.get_or_create(node_id).record_success(rtt_ms)

    def record_failure(self, node_id: str) -> None:
        self.get_or_create(node_id).record_failure()

    # ── Score computation ─────────────────────────────────────────

    def score(self, node_id: str) -> float:
        """
        Return composite reliability score for ``node_id``.

        Returns 0.5 (neutral) for unknown peers with no history.
        """
        stats = self._stats.get(node_id)
        if stats is None:
            return 0.5

        rtt_score     = self._rtt_score(stats)
        success_score = stats.success_rate
        recency_score = self._recency_score(stats)
        streak_score  = self._streak_score(stats)

        return (
            0.40 * rtt_score
            + 0.35 * success_score
            + 0.15 * recency_score
            + 0.10 * streak_score
        )

    def rank_peers(self, node_ids: list[str]) -> list[str]:
        """Return ``node_ids`` sorted by score descending (best first)."""
        return sorted(node_ids, key=self.score, reverse=True)

    def evict_candidate(self, node_ids: list[str]) -> str | None:
        """Return the node_id with the lowest score — eviction candidate."""
        if not node_ids:
            return None
        return min(node_ids, key=self.score)

    # ── Score sub-components ──────────────────────────────────────

    @staticmethod
    def _rtt_score(stats: PeerStats) -> float:
        """Maps RTT EWMA to [0, 1]. No samples → 0.5 (neutral)."""
        if stats.rtt_samples == 0:
            return 0.5
        rtt = max(0.0, stats.rtt_ewma_ms)
        if rtt <= RTT_IDEAL_MS:
            return 1.0
        if rtt >= RTT_WORST_MS:
            return 0.0
        # Logarithmic decay between ideal and worst
        log_pos = math.log(rtt / RTT_IDEAL_MS) / math.log(RTT_WORST_MS / RTT_IDEAL_MS)
        return max(0.0, 1.0 - log_pos)

    @staticmethod
    def _recency_score(stats: PeerStats) -> float:
        """
        Exponential decay: score = 0.5^(age / DECAY_HALF_LIFE).
        A peer last seen 1 hour ago scores 0.5; 2 hours ago → 0.25.
        """
        age_seconds = time.time() - stats.last_seen
        return 0.5 ** (age_seconds / DECAY_HALF_LIFE)

    @staticmethod
    def _streak_score(stats: PeerStats) -> float:
        """
        Penalise consecutive failures exponentially.
        0 failures → 1.0; 5 failures → ~0.03; 10+ → ~0.001.
        """
        k = stats.consecutive_failures
        return math.exp(-0.5 * k)
