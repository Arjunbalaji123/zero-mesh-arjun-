"""
Unit tests — Phase 7: Prometheus Metrics & Monitoring
  - Metric counters, gauges, histograms
  - Metric export formatting
"""

from __future__ import annotations

from prometheus_client import generate_latest

from zeromesh.monitoring.metrics import METRICS, ZeroMeshMetrics


class TestZeroMeshMonitoring:
    def test_metrics_singleton(self):
        assert isinstance(METRICS, ZeroMeshMetrics)
        assert METRICS.uploads_total is not None
        assert METRICS.downloads_total is not None
        assert METRICS.active_peers is not None
        assert METRICS.storage_bytes is not None

    def test_counter_increments(self):
        before = METRICS.messages_sent_total._value.get()
        METRICS.messages_sent_total.inc(5)
        after = METRICS.messages_sent_total._value.get()
        assert after == before + 5

    def test_gauge_set(self):
        METRICS.active_peers.set(42)
        assert METRICS.active_peers._value.get() == 42
        METRICS.active_peers.set(10)
        assert METRICS.active_peers._value.get() == 10

    def test_histogram_observe(self):
        METRICS.upload_duration_seconds.observe(0.125)
        METRICS.peer_rtt_seconds.observe(0.015)

    def test_prometheus_text_export(self):
        output = generate_latest().decode("utf-8")
        assert "zeromesh_uploads_total" in output
        assert "zeromesh_active_peers" in output
        assert "zeromesh_storage_bytes" in output
