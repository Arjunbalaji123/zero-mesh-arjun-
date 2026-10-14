# AUDIT.md — Comprehensive Codebase Audit of ZeroMesh

**Project**: ZeroMesh — Trust-Aware Decentralized P2P Encrypted File System  
**Course**: Computer Networks (20MSS52)  
**Author/Auditor**: Senior Distributed-Systems & Security Engineering Team  
**Date**: October 2026  
**Scope**: Full codebase audit (`zeromesh/core`, `zeromesh/crypto`, `zeromesh/dht`, `zeromesh/network`, `zeromesh/storage`, `zeromesh/monitoring`, `zeromesh/api`, `zeromesh/cli.py`, `benchmarks`, `tests`).

---

## Executive Summary

ZeroMesh presents a clean, modular foundation for an academic P2P encrypted storage system, implementing fundamental Kademlia routing, AES-GCM chunk encryption, SHA-256 content addressing, and an async TCP protocol. However, a rigorous distributed-systems and adversarial analysis reveals critical security vulnerabilities, concurrency bugs, missing fault-tolerance primitives, and architectural gaps compared to the project abstract.

The findings are classified into 5 categories and ranked by severity:
- **Critical (P0)**: Cryptographic leakage / broken trust assumptions / data loss / remote crash.
- **High (P1)**: Concurrency race conditions / DHT correctness flaws / Sybil vulnerabilities.
- **Medium (P2)**: Blocking event-loop calls / missing error-handling & validation / resource leaks.
- **Low (P3)**: Telemetry gaps / testing coverage omissions / ergonomics.

---

## Ranked Findings

### [CRITICAL - P0] Security Vulnerabilities

#### 1. Plaintext Chunk Hashing instead of Ciphertext Content Addressing (Convergent/Plaintext Oracle)
- **Location**: `zeromesh/crypto/engine.py:41`, `zeromesh/crypto/engine.py:113`, `zeromesh/storage/file_manager.py:92-95`
- **Issue**: `EncryptedChunk.content_id = sha256_hash(plaintext)`. The DHT key and the storage identifier sent across unauthenticated peers is the hash of the *plaintext* chunk. 
- **Impact**:
  1. Untrusted peers holding chunks learn the hash of plaintext blocks. Any peer with access to dictionary attacks or known plaintexts can determine what file contents are stored or transferred.
  2. Peers can neither verify chunk integrity before decryption nor during replication between peers because only the key-holder can decrypt to check `sha256_hash(plaintext)`. Malicious peers can serve corrupted ciphertexts that only fail at the client download stage.
- **Remediation**:
  - Implement *Encrypt-then-Hash*: Encrypt chunk `C = Encrypt(K, P)` with random nonce, then compute Content ID `CID = sha256(nonce || C)` (or `sha256(C)`).
  - Storage and DHT peers verify `CID` directly on `STORE_CHUNK`, `GET_CHUNK`, and replication without possessing the key.

#### 2. Key Management & Separation Missing
- **Location**: `zeromesh/node.py:59`, `zeromesh/storage/file_manager.py:75-76`
- **Issue**: Each node generates a single ephemeral random key (`self.key = key or generate_key()`) upon node start. There is no concept of a Data Encryption Key (DEK) per file, nor a Key Encryption Key (KEK) derived from user passphrases using Argon2id or scrypt.
- **Impact**:
  - If a node restarts without saving keys, files become permanently irrecoverable.
  - Sharing files requires sharing the node's entire master key.
  - No separation between chunk storage identities and decryption capability.
- **Remediation**:
  - Create `zeromesh/crypto/key_manager.py`.
  - Implement per-file DEKs wrapped with user passphrase-derived KEK via Argon2id.
  - Separate manifest keys, storage keys, and support user-to-user sharing via public-key wrapping (X25519/Ed25519).

#### 3. Unauthenticated Transport & Identity Impersonation (Sybil / Man-in-the-Middle)
- **Location**: `zeromesh/network/connection.py`, `zeromesh/network/protocol.py`, `zeromesh/node.py:113-131`
- **Issue**:
  - Raw unauthenticated TCP sockets. Node IDs are self-reported strings (`msg.payload.get("node_id")` or `NodeID.from_address(host, port)`).
  - No cryptographic proof of ownership for node IDs.
  - Any peer can claim to be any node ID, poison routing tables, eclipse targets, or spoof `STORE_ACK` / `CHUNK_DATA`.
- **Remediation**:
  - Generate node identities from Ed25519 keypairs (`node_id = sha256(public_key)`).
  - Sign wire messages or conduct an authenticated handshake with replay protection (random session nonces and timestamps).
  - Enforce bucket diversity limits (limit peers per /16 IPv4 subnet).

#### 4. Malformed Packet Deserialization & Lack of Schema Validation
- **Location**: `zeromesh/network/protocol.py:247`, `zeromesh/node.py:160-185`
- **Issue**:
  - `msgpack.unpackb(body, raw=False)` unpacks arbitrary dictionaries.
  - Handlers directly index dictionary keys without schema validation (e.g. `msg.payload["content_id"]`, `msg.payload["nonce"]`).
  - If a remote peer sends `{}` or integers instead of bytes for `nonce`, an unhandled `KeyError` or `TypeError` crashes or terminates the peer connection handler.
- **Remediation**:
  - Add explicit message payload validators and schemas with type & bounds checking.

---

### [HIGH - P1] Concurrency & Asyncio Race Conditions

#### 5. Port Binding Race Condition in Server Shutdown & Tests
- **Location**: `zeromesh/network/server.py:90-95`, `zeromesh/node.py:363`
- **Issue**:
  - In `NodeServer.stop()`, `self._server.close()` and `await self._server.wait_closed()` is called, but inbound connection tasks in `self._tasks` are gathered without timeout or cancellation before sockets are fully freed.
  - In rapid start/stop scenarios (such as pytest test fixtures in `test_phase6_api.py`), the socket stays in `TIME_WAIT` or background coroutines hold file descriptors, causing `[Errno 98] Address already in use`.
- **Remediation**:
  - Explicitly cancel all active connection tasks during `server.stop()`.
  - Add dynamic/ephemeral port allocation option for tests (`port=0`).
  - Set `SO_REUSEADDR` and ensure fast socket teardown.

#### 6. Missing Concurrency Control in Chunk/File Assembler & Parallel Fetch
- **Location**: `zeromesh/storage/file_manager.py:160-175`, `zeromesh/core/chunker.py:170-195`
- **Issue**:
  - `FileAssembler.add_chunk(index, data)` mutates an in-memory dictionary `_chunks` without thread-safety or streaming backpressure.
  - For large files, downloading 10,000 chunks concurrently loads the entire file into memory before writing to disk (`assembler.write_to(out_path)`), causing OOM crashes.
- **Remediation**:
  - Implement streaming chunker & assembler with async generator pipelines and bounded semaphore concurrency (e.g. max 5 concurrent chunk downloads).
  - Write directly to temp file at chunk offsets (`seek(index * chunk_size)`).

#### 7. Kademlia Routing Table Bucket Eviction Race
- **Location**: `zeromesh/dht/kbucket.py:92-120`, `zeromesh/dht/routing_table.py:54-73`
- **Issue**:
  - When `KBucket.add_or_update` returns `False` (bucket is full), `RoutingTable` does not initiate the asynchronous ping-before-evict procedure mandated by the Kademlia specification.
  - Instead, the peer is just discarded or pushed to replacement cache, violating LRU survivability of long-lived nodes.
- **Remediation**:
  - Implement async `ping_before_evict` worker in `RoutingTable` / `ZeroMeshNode`: ping LRS peer; if unresponsive, evict and promote replacement.

---

### [HIGH - P1] Distributed Systems & Fault Tolerance Gaps

#### 8. Lack of Dynamic Replication & Background Repair Loop
- **Location**: `zeromesh/storage/file_manager.py:97-105`
- **Issue**:
  - Replication is strictly "fire-and-forget" at upload time (`REPLICATION_FACTOR = 3`).
  - When peers leave or fail, chunks are not re-replicated. No background audit detects degraded chunk availability.
  - Chunks stored on departed nodes are lost forever once count drops below 1.
- **Remediation**:
  - Build `zeromesh/replication/replication_manager.py`.
  - Implement active replica health checks (periodic challenge-response audits).
  - Automated repair loop that detects under-replicated chunks (`count < k`) and replicates them to nearest healthy peers.

#### 9. Absence of Erasure Coding (Reed-Solomon)
- **Location**: `zeromesh/core/chunker.py`
- **Issue**:
  - Only full chunk replication is supported. To survive $f$ node failures, full replication requires $f+1$ copies (200%-300% storage overhead).
- **Remediation**:
  - Implement configurable Reed-Solomon erasure coding ($k=4, m=2$) using Galois Field arithmetic or `zfec` algorithm in pure Python/C.
  - Benchmark storage redundancy vs recovery performance.

#### 10. Peer Scorer Model Limitations & Integrity Failure Ignored
- **Location**: `zeromesh/network/peer_scorer.py:137-158`
- **Issue**:
  - `PeerScorer` has no concept of chunk integrity failures. A peer that delivers corrupted or tampered chunk data is not penalized differently from a slow peer.
  - Scores are not persisted across node restarts.
  - Configurable weights and cold-start priors are absent.
- **Remediation**:
  - Add explicit `record_integrity_failure(node_id)`. Immediate severe penalty (-0.6 to -1.0) and progressive temporary blacklisting.
  - Externalize weights to configuration (`ScorerConfig`).

---

### [MEDIUM - P2] Networking, Performance & DHT Correctness

#### 11. Event Loop Blocking on Heavy Crypto Operations
- **Location**: `zeromesh/storage/file_manager.py:93`, `zeromesh/crypto/engine.py:89`
- **Issue**:
  - AES-GCM encryption/decryption, SHA-256 hashing, and Argon2/PBKDF2 key derivation run synchronously on the asyncio event loop thread.
  - During large file uploads/downloads or heavy benchmark load, the event loop freezes, causing peer PINGs to time out and TCP disconnects.
- **Remediation**:
  - Wrap CPU-bound cryptography and disk file I/O in `asyncio.to_thread` / `loop.run_in_executor`.

#### 12. Protocol Framing Missing Protocol Version
- **Location**: `zeromesh/network/protocol.py:5-19`
- **Issue**:
  - Wire header is `[uint32 body_len][uint8 msg_type]`. It has no protocol version byte.
  - Any future protocol evolution will break backward compatibility.
- **Remediation**:
  - Update header format: `[uint32 body_len][uint8 version][uint8 msg_type]` (version = 1).

#### 13. Lack of Rate Limiting & Connection Caps
- **Location**: `zeromesh/network/server.py:74-80`, `zeromesh/node.py:91-110`
- **Issue**:
  - Inbound connection acceptance is unbounded (`backlog=100`, no connection limit).
  - Malicious peers can exhaust system file descriptors and memory (DoS).
- **Remediation**:
  - Add `max_connections` cap, per-IP connection limits, and token-bucket rate limiting on inbound messages.

---

### [LOW - P3] Observability, Testing & Ergonomics

#### 14. Missing Evaluation Harness for Course Deliverable
- **Location**: `benchmarks/`
- **Issue**:
  - The repo only contains a rudimentary single-process `benchmark_throughput.py`.
  - Missing the multi-node automated evaluation harness specified in project abstract: peer discovery vs network size (10..100 peers), retrieval throughput, replication vs erasure coding, fault-injection node killing (0%..50%), and trust-aware vs random peer selection comparison.
- **Remediation**:
  - Create `benchmarks/evaluation_harness.py` exporting metrics, CSVs, and matplotlib graphs.

#### 15. CLI Missing `--json` Output and Error Diagnostics
- **Location**: `zeromesh/cli.py`
- **Issue**:
  - CLI only prints Rich text; lacks scriptable `--json` output, correlation IDs, and file sharing commands.

---

## Audit Matrix Summary

| ID | Module | Finding | Severity | Status |
|:---|:---|:---|:---:|:---:|
| SEC-01 | `crypto/engine.py` | Plaintext content hashing (CID leaks plaintext) | **P0** | Planned Milestone 1 |
| SEC-02 | `crypto/key_manager.py` | Missing key manager, DEK wrapping & Argon2id KDF | **P0** | Planned Milestone 1 |
| SEC-03 | `network/protocol.py` | Unauthenticated transport, no identity signatures | **P0** | Planned Milestone 1 |
| SEC-04 | `network/protocol.py` | Unvalidated msgpack payloads causing crashes | **P1** | Planned Milestone 1 |
| NET-01 | `network/server.py` | Port binding race & unclean task cancellation | **P1** | Planned Milestone 1 |
| DHT-01 | `dht/routing_table.py`| Ping-before-evict async policy missing | **P1** | Planned Milestone 3 |
| REP-01 | `replication/` | No background repair loop or health audits | **P1** | Planned Milestone 2 |
| TRU-01 | `network/peer_scorer.py`| Missing integrity penalties & blacklist mechanism | **P0** | Planned Milestone 2 |
| FS-01 | `storage/file_manager.py`| Non-streaming memory buffering (OOM risk) | **P1** | Planned Milestone 4 |
| PERF-01| `storage/file_manager.py`| Event loop blocking on crypto/hash operations | **P2** | Planned Milestone 4 |
| EVAL-01| `benchmarks/` | Missing multi-node benchmark & fault injection harness | **P0** | Planned Milestone 5 |
| DOC-01 | `docs/` | Incomplete architectural & evaluation documentation | **P1** | Planned Milestone 6 |

---

## Action Plan & Implementation Milestones

1. **Milestone 1 — Security Hardening & Robust Protocol (Priority 1)**:
   - Dedicated `KeyManager` with Argon2id KEK, per-file DEKs, and key serialization.
   - Encrypt-then-Hash content addressing (`CID = sha256(ciphertext)`).
   - Ed25519 node identity & signature verification on protocol messages.
   - Wire protocol v2: version byte, schema validation, message size caps, rate limiting.
   - Fix server socket port reuse & task cancellation in `NodeServer`.

2. **Milestone 2 — Trust-Aware Peer Scoring & Blacklisting (Priority 2)**:
   - Full tunable scoring model: EWMA RTT, uptime, success rate, time decay.
   - Severe integrity-failure penalty & automatic temporary blacklist.
   - Integration with retrieval, replica placement, and routing table eviction.
   - Expose scores and weights via REST API and dashboard.

3. **Milestone 3 — Replication Manager, Background Repair & Erasure Coding (Priority 3)**:
   - `ReplicationManager` with placement across closest/trusted peers.
   - Periodic chunk health audits (challenge-response proof).
   - Dynamic repair loop for degraded chunks.
   - Reed-Solomon erasure coding module ($k=4, m=2$).

4. **Milestone 4 — Asynchronous & Streaming File Pipeline (Priority 4 & 5)**:
   - Offload crypto/hashing to executor threads.
   - Streaming chunking and disk assembly (constant memory).
   - File sharing via recipient public key wrapping.
   - Resumable transfers and deduplication.

5. **Milestone 5 — Evaluation Harness & Benchmarks (Priority 7)**:
   - Multi-node simulation framework (10, 25, 50, 100 virtual peers).
   - Automated benchmark suites: discovery latency, retrieval throughput, fault recovery under node kills (0%-50%), trust-aware vs random selection.
   - CSV results export + matplotlib graph generator.

6. **Milestone 6 — Observability, UX, Tests & Documentation (Priority 6, 8, 9)**:
   - Prometheus metrics extensions (histograms, integrity counts, repair events).
   - Enhanced Web Dashboard (fault injection, live scores, topology).
   - Comprehensive test suite: pytest, pytest-asyncio, hypothesis property tests, fault injection.
   - Documentation: `docs/DESIGN.md`, `docs/EVALUATION.md`, `demo.sh`, updated `README.md`.
