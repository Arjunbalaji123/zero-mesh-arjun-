"""
ZeroMesh Monitoring — Prometheus Metrics
==========================================
Central registry of all application-level counters and gauges.

Metric naming follows the Prometheus convention:
  zeromesh_<subsystem>_<name>_<unit>

Usage::

    from zeromesh.monitoring.metrics import METRICS
    METRICS.uploads_total.inc()
    METRICS.active_peers.set(42)
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import Counter, Gauge, Histogram


@dataclass
class ZeroMeshMetrics:
    # ── File transfer ─────────────────────────────────────────────
    uploads_total: Counter
    downloads_total: Counter
    bytes_uploaded: Counter
    bytes_downloaded: Counter
    upload_duration_seconds: Histogram
    download_duration_seconds: Histogram

    # ── Network ───────────────────────────────────────────────────
    active_connections: Gauge
    messages_sent_total: Counter
    messages_received_total: Counter
    peer_rtt_seconds: Histogram

    # ── DHT ───────────────────────────────────────────────────────
    active_peers: Gauge
    dht_lookups_total: Counter
    dht_lookup_duration_seconds: Histogram

    # ── Storage ───────────────────────────────────────────────────
    chunks_stored_total: Counter
    chunks_retrieved_total: Counter
    storage_bytes: Gauge


def _build_metrics() -> ZeroMeshMetrics:
    buckets = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
    return ZeroMeshMetrics(
        uploads_total=Counter(
            "zeromesh_uploads_total", "Total file uploads"
        ),
        downloads_total=Counter(
            "zeromesh_downloads_total", "Total file downloads"
        ),
        bytes_uploaded=Counter(
            "zeromesh_bytes_uploaded_total", "Total bytes uploaded"
        ),
        bytes_downloaded=Counter(
            "zeromesh_bytes_downloaded_total", "Total bytes downloaded"
        ),
        upload_duration_seconds=Histogram(
            "zeromesh_upload_duration_seconds", "File upload latency", buckets=buckets
        ),
        download_duration_seconds=Histogram(
            "zeromesh_download_duration_seconds", "File download latency", buckets=buckets
        ),
        active_connections=Gauge(
            "zeromesh_active_connections", "Current open peer connections"
        ),
        messages_sent_total=Counter(
            "zeromesh_messages_sent_total", "Total messages sent"
        ),
        messages_received_total=Counter(
            "zeromesh_messages_received_total", "Total messages received"
        ),
        peer_rtt_seconds=Histogram(
            "zeromesh_peer_rtt_seconds", "Peer round-trip time", buckets=buckets
        ),
        active_peers=Gauge(
            "zeromesh_active_peers", "Peers currently in routing table"
        ),
        dht_lookups_total=Counter(
            "zeromesh_dht_lookups_total", "Total Kademlia lookups performed"
        ),
        dht_lookup_duration_seconds=Histogram(
            "zeromesh_dht_lookup_duration_seconds",
            "Kademlia lookup latency",
            buckets=buckets,
        ),
        chunks_stored_total=Counter(
            "zeromesh_chunks_stored_total", "Total chunks stored locally"
        ),
        chunks_retrieved_total=Counter(
            "zeromesh_chunks_retrieved_total", "Total chunks retrieved"
        ),
        storage_bytes=Gauge(
            "zeromesh_storage_bytes", "Total bytes currently stored"
        ),
    )


# Singleton — import and use directly
METRICS: ZeroMeshMetrics = _build_metrics()
