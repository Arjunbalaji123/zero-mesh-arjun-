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
class ScorerConfig:
    """Configurable weights and thresholds for peer trust scoring."""
    weight_rtt: float = 0.30
    weight_success: float = 0.30
    weight_recency: float = 0.15
    weight_streak: float = 0.10
    weight_integrity: float = 0.15
    integrity_penalty: float = 0.50
    blacklist_threshold_failures: int = 2
    blacklist_duration_seconds: float = 300.0   # 5 minutes
    cold_start_prior: float = 0.50


@dataclass
class PeerStats:
    """
    Mutable runtime statistics for a single peer.
    """
    node_id: str

    # Message exchange counters
    total_requests:   int   = 0
    successful:       int   = 0
    failed:           int   = 0
    consecutive_failures: int = 0
    integrity_failures:   int = 0

    # RTT tracking (Exponentially Weighted Moving Average)
    rtt_ewma_ms:  float = 0.0
    rtt_samples:  int   = 0

    # Timestamps
    first_seen:   float = field(default_factory=time.time)
    last_seen:    float = field(default_factory=time.time)
    blacklisted_until: float = 0.0

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

    def record_integrity_failure(self, blacklist_duration: float = 300.0) -> None:
        """Record corrupt/tampered chunk delivery with immediate penalty."""
        self.total_requests += 1
        self.failed += 1
        self.consecutive_failures += 3
        self.integrity_failures += 1
        self.blacklisted_until = time.time() + blacklist_duration

    def is_blacklisted(self) -> bool:
        """Returns True if the peer is currently blacklisted."""
        return time.time() < self.blacklisted_until

    def _update_rtt(self, sample_ms: float) -> None:
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
        score = w_rtt * rtt_score
              + w_success * success_score
              + w_recency * recency_score
              + w_streak * streak_score
              + w_integrity * integrity_score
    """

    def __init__(self, config: ScorerConfig | None = None) -> None:
        self.config = config or ScorerConfig()
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

    def record_integrity_failure(self, node_id: str) -> None:
        """Immediate severe penalty and blacklisting on chunk hash mismatch."""
        self.get_or_create(node_id).record_integrity_failure(
            blacklist_duration=self.config.blacklist_duration_seconds
        )

    def is_blacklisted(self, node_id: str) -> bool:
        stats = self._stats.get(node_id)
        return stats.is_blacklisted() if stats else False

    # ── Score computation ─────────────────────────────────────────

    def score(self, node_id: str) -> float:
        """
        Return composite reliability score for ``node_id``.
        Returns cold_start_prior for unknown peers with no history.
        Blacklisted peers receive score 0.0.
        """
        stats = self._stats.get(node_id)
        if stats is None:
            return self.config.cold_start_prior

        if stats.is_blacklisted():
            return 0.0

        cfg = self.config
        rtt_score     = self._rtt_score(stats)
        success_score = stats.success_rate
        recency_score = self._recency_score(stats)
        streak_score  = self._streak_score(stats)
        integrity_score = max(0.0, 1.0 - (stats.integrity_failures * cfg.integrity_penalty))

        raw_score = (
            cfg.weight_rtt * rtt_score
            + cfg.weight_success * success_score
            + cfg.weight_recency * recency_score
            + cfg.weight_streak * streak_score
            + cfg.weight_integrity * integrity_score
        )
        return max(0.0, min(1.0, raw_score))

    def rank_peers(self, node_ids: list[str]) -> list[str]:
        """Return ``node_ids`` sorted by score descending (best first), excluding blacklisted."""
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
        log_pos = math.log(rtt / RTT_IDEAL_MS) / math.log(RTT_WORST_MS / RTT_IDEAL_MS)
        return max(0.0, 1.0 - log_pos)

    @staticmethod
    def _recency_score(stats: PeerStats) -> float:
        age_seconds = time.time() - stats.last_seen
        return float(0.5 ** (age_seconds / DECAY_HALF_LIFE))

    @staticmethod
    def _streak_score(stats: PeerStats) -> float:
        k = stats.consecutive_failures
        return math.exp(-0.5 * k)
