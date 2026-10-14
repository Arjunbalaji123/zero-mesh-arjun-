import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Node defaults
DEFAULT_P2P_PORT = int(os.getenv("ZEROMESH_P2P_PORT", "9000"))
DEFAULT_API_PORT = int(os.getenv("ZEROMESH_API_PORT", "8000"))

# Storage & Replication Config
CHUNK_SIZE_BYTES = int(os.getenv("ZEROMESH_CHUNK_SIZE", str(1 * 1024 * 1024)))  # 1 MB default
REPLICATION_FACTOR = int(os.getenv("ZEROMESH_REPLICATION_FACTOR", "3"))

# Kademlia DHT parameters
K_BUCKET_SIZE = int(os.getenv("ZEROMESH_K_BUCKET_SIZE", "20"))
NODE_ID_BITS = 160
ALPHA_CONCURRENCY = 3

# Database configuration
DB_NAME = os.getenv("ZEROMESH_DB_NAME", "zeromesh.db")
DB_PATH = DATA_DIR / DB_NAME
