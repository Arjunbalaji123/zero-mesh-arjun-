#!/usr/bin/env bash
# ==============================================================================
# ZeroMesh Course Demo Walkthrough (Computer Networks 20MSS52)
# Demonstrates:
#   1. Spawning 5 decentralized peer nodes
#   2. DHT bootstrapping & mesh formation
#   3. File upload & chunk replication across peers
#   4. Fault injection: Killing 2 peers & corrupting a chunk
#   5. Trust-aware recovery & verified download
# ==============================================================================

set -e

DEMO_DIR=$(mktemp -d /tmp/zeromesh_demo_XXXXXX)
echo "=== ZeroMesh Course Live Demonstration ==="
echo "Working directory: $DEMO_DIR"

cleanup() {
    echo "Shutting down nodes..."
    kill $(jobs -p) 2>/dev/null || true
    rm -rf "$DEMO_DIR"
    echo "Cleanup complete."
}
trap cleanup EXIT

# 1. Start Bootstrap Node (Node 1)
echo ""
echo "[Step 1] Starting Bootstrap Node (Node 1) on :7601..."
./venv/bin/python -m uvicorn zeromesh.api.app:app --port 8001 &
PID1=$!
sleep 1

# 2. Run Python Interactive Demo Walkthrough
echo ""
echo "[Step 2] Executing Multi-Node Mesh Walkthrough..."
./venv/bin/python scripts/demo_walkthrough.py

echo ""
echo "=== Course Demo Completed with 100% Verification! ==="

