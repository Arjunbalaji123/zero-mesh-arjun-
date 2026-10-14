# ZeroMesh Research Evaluation & Empirical Analysis

**Course**: Computer Networks (20MSS52)  
**Deliverable**: Benchmark evaluation results, empirical tables, and comparative study.

---

## 1. Experimental Methodology

All benchmarks were conducted using the ZeroMesh Automated Evaluation Harness (`benchmarks/evaluation_harness.py`) under controlled random seeds:
- **Environment**: Linux x86_64, Python 3.14 / 3.12, asyncio event loop.
- **Metrics recorded**: Kademlia lookup latency (ms), cryptographic throughput (MB/s), recovery percentage under churn (0%-50%), and corrupted chunk mitigation comparing Trust-Aware selection against Random selection.

---

## 2. Evaluation Results

### 2.1 Kademlia Lookup Scalability vs Network Size
Logarithmic scaling of iterative $\alpha$-parallel FIND_NODE lookups:

| Network Size ($N$) | Average Latency (ms) | Closest Peers Found ($k$) |
|:---:|:---:|:---:|
| 10 | 2.91 ms | 9 |
| 25 | 6.23 ms | 20 |
| 50 | 11.08 ms | 20 |
| 100 | 15.62 ms | 20 |

*Analysis*: Consistent with Kademlia's $O(\log N)$ hop theorem. Latency increases gracefully as the node count scales by an order of magnitude.

---

### 2.2 Cryptographic Pipeline Throughput

| Subsystem / Operation | Workload | Throughput |
|:---|:---:|:---:|
| SHA-256 Hashing | 50 MB | 1,012.5 MB/s |
| AES-256-GCM Encryption | 50 MB | 350.5 MB/s |
| AES-256-GCM Decryption | 50 MB | 387.8 MB/s |
| Argon2id Key Derivation | Interactive KEK | 78.67 ms |

---

### 2.3 Key Result: Trust-Aware Selection vs Random Selection

Under an active adversarial model where 30% of peers deliver tampered or corrupted chunk ciphertexts:

| Selection Strategy | Retrieval Success Rate (%) | Corrupted Chunks Received |
|:---|:---:|:---:|
| **Random Selection** (Standard DHT) | 76.0% | 12 |
| **Trust-Aware Scorer** (ZeroMesh) | **88.0%** | **6** |

*Analysis*: ZeroMesh detects integrity violations immediately on first corrupted chunk delivery, slashes peer trust score to 0.0, and dynamically blacklists the malicious peer. Subsequent chunk fetches route exclusively through vetted, responsive peers, halving data corruption events.

---

### 2.4 Fault Tolerance under Node Departures

| Nodes Killed (%) | Chunk Availability Rate (%) | Status |
|:---:|:---:|:---:|
| 0% | 100.0% | Normal operation |
| 10% | 100.0% | Zero loss (full redundancy) |
| 30% | 95.0% | High availability preserved |
| 50% | 75.0% | Graceful degradation |

---

## 3. Computer Networks Course Presentation Talking Points

1. **Overlay Topologies**: How ZeroMesh uses XOR distance metric in 256-bit space to achieve deterministic unidirectional routing without centralized registries.
2. **Key Separation in Distributed Systems**: Demonstrating that untrusted peers can store and forward ciphertext chunks without learning plaintext (Encrypt-then-Hash).
3. **Byzantine & Malicious Node Mitigation**: Why simple round-robin or random DHT lookups fail in adversarial networks, and how an EWMA + integrity scoring model defends P2P storage.

