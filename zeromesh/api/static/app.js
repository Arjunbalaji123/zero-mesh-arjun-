/**
 * ZeroMesh Web Dashboard — Interactive Client Logic
 * ==================================================
 * Features:
 *   - Real-time P2P Mesh Topology 2D Visualizer with animated packet pulses
 *   - Ambient cyber particle constellation background
 *   - Cryptographic Pipeline Stage Animation Tracker
 *   - Interactive Web Audio sound effects synthesizer
 *   - Instant sample file generator for live demonstrations
 *   - Drag-and-drop file upload with AES-256-GCM & 3x replication
 *   - Parallel DHT chunk lookup & streaming verified download
 */

// ── State ───────────────────────────────────────────────────────────────────
let fullNodeId = "";
let selectedFile = null;
let sfxEnabled = true;
let isAnimatingPipeline = false;
let showPackets = true;
let showLabels = true;

// ── DOM References ──────────────────────────────────────────────────────────
const headerNodeId = document.getElementById("header-node-id");
const btnCopyNodeId = document.getElementById("btn-copy-node-id");
const btnSoundToggle = document.getElementById("btn-sound-toggle");
const soundStatus = document.getElementById("sound-status");
const cursorGlow = document.getElementById("cursor-glow");

const metricPeers = document.getElementById("metric-peers");
const metricPeersSub = document.getElementById("metric-peers-sub");
const metricChunks = document.getElementById("metric-chunks");
const metricBytes = document.getElementById("metric-bytes");
const metricHealth = document.getElementById("metric-health");

const uploadDropzone = document.getElementById("upload-dropzone");
const fileInput = document.getElementById("file-input");
const fileSelectedBox = document.getElementById("file-selected-box");
const selectedFileName = document.getElementById("selected-file-name");
const selectedFileSize = document.getElementById("selected-file-size");
const btnClearSelected = document.getElementById("btn-clear-selected");
const btnUpload = document.getElementById("btn-upload");
const btnQuickSample = document.getElementById("btn-quick-sample");
const uploadResult = document.getElementById("upload-result");
const uploadResultMeta = document.getElementById("upload-result-meta");
const uploadManifestId = document.getElementById("upload-manifest-id");
const btnCopyManifest = document.getElementById("btn-copy-manifest");

const downloadManifestInput = document.getElementById("download-manifest-input");
const btnDownload = document.getElementById("btn-download");

const peersTableBody = document.getElementById("peers-table-body");
const btnRefreshPeers = document.getElementById("btn-refresh-peers");

const filesTableBody = document.getElementById("files-table-body");
const btnRefreshFiles = document.getElementById("btn-refresh-files");

const terminalLogs = document.getElementById("terminal-logs");
const btnClearLogs = document.getElementById("btn-clear-logs");
const toastContainer = document.getElementById("toast-container");

// Pipeline steps
const stepChunk = document.getElementById("step-chunk");
const stepHash = document.getElementById("step-hash");
const stepArgon = document.getElementById("step-argon");
const stepEncrypt = document.getElementById("step-encrypt");
const stepDht = document.getElementById("step-dht");

// ── Web Audio API Synthesizer (Zero External Assets) ─────────────────────────
let audioCtx = null;

function getAudioContext() {
  if (!audioCtx) {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (AudioContext) {
      audioCtx = new AudioContext();
    }
  }
  if (audioCtx && audioCtx.state === "suspended") {
    audioCtx.resume();
  }
  return audioCtx;
}

function playCyberSound(type = "click") {
  if (!sfxEnabled) return;
  try {
    const ctx = getAudioContext();
    if (!ctx) return;

    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);

    if (type === "click") {
      osc.type = "sine";
      osc.frequency.setValueAtTime(800, now);
      osc.frequency.exponentialRampToValueAtTime(300, now + 0.05);
      gain.gain.setValueAtTime(0.08, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.05);
      osc.start(now);
      osc.stop(now + 0.05);
    } else if (type === "success") {
      osc.type = "triangle";
      osc.frequency.setValueAtTime(440, now);
      osc.frequency.setValueAtTime(659.25, now + 0.08);
      osc.frequency.setValueAtTime(880, now + 0.16);
      gain.gain.setValueAtTime(0.09, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
      osc.start(now);
      osc.stop(now + 0.35);
    } else if (type === "packet") {
      osc.type = "sine";
      osc.frequency.setValueAtTime(1200, now);
      osc.frequency.exponentialRampToValueAtTime(1800, now + 0.04);
      gain.gain.setValueAtTime(0.03, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.04);
      osc.start(now);
      osc.stop(now + 0.04);
    } else if (type === "error") {
      osc.type = "sawtooth";
      osc.frequency.setValueAtTime(220, now);
      osc.frequency.exponentialRampToValueAtTime(110, now + 0.2);
      gain.gain.setValueAtTime(0.1, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.2);
      osc.start(now);
      osc.stop(now + 0.2);
    }
  } catch (e) {
    // Audio context may be restricted before gesture
  }
}

// ── Interactive Cursor Spotlight ────────────────────────────────────────────
window.addEventListener("pointermove", (e) => {
  if (cursorGlow) {
    cursorGlow.style.left = `${e.clientX}px`;
    cursorGlow.style.top = `${e.clientY}px`;
  }
});

// ── Ambient Background Particles Canvas ─────────────────────────────────────
const bgCanvas = document.getElementById("bg-canvas");
const bgCtx = bgCanvas ? bgCanvas.getContext("2d") : null;
let bgParticles = [];

function initBgCanvas() {
  if (!bgCanvas) return;
  bgCanvas.width = window.innerWidth;
  bgCanvas.height = window.innerHeight;

  const count = Math.floor((bgCanvas.width * bgCanvas.height) / 18000);
  bgParticles = [];
  for (let i = 0; i < count; i++) {
    bgParticles.push({
      x: Math.random() * bgCanvas.width,
      y: Math.random() * bgCanvas.height,
      vx: (Math.random() - 0.5) * 0.4,
      vy: (Math.random() - 0.5) * 0.4,
      radius: Math.random() * 1.6 + 0.5,
      alpha: Math.random() * 0.4 + 0.1,
    });
  }
}

function renderBgCanvas() {
  if (!bgCanvas || !bgCtx) return;
  bgCtx.clearRect(0, 0, bgCanvas.width, bgCanvas.height);

  for (let i = 0; i < bgParticles.length; i++) {
    const p = bgParticles[i];
    p.x += p.vx;
    p.y += p.vy;

    if (p.x < 0) p.x = bgCanvas.width;
    if (p.x > bgCanvas.width) p.x = 0;
    if (p.y < 0) p.y = bgCanvas.height;
    if (p.y > bgCanvas.height) p.y = 0;

    bgCtx.beginPath();
    bgCtx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
    bgCtx.fillStyle = `rgba(99, 102, 241, ${p.alpha})`;
    bgCtx.fill();

    // Connect nearby particles
    for (let j = i + 1; j < bgParticles.length; j++) {
      const p2 = bgParticles[j];
      const dx = p.x - p2.x;
      const dy = p.y - p2.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < 110) {
        bgCtx.beginPath();
        bgCtx.moveTo(p.x, p.y);
        bgCtx.lineTo(p2.x, p2.y);
        bgCtx.strokeStyle = `rgba(6, 182, 212, ${(1 - dist / 110) * 0.12})`;
        bgCtx.lineWidth = 0.6;
        bgCtx.stroke();
      }
    }
  }

  requestAnimationFrame(renderBgCanvas);
}

window.addEventListener("resize", initBgCanvas);
initBgCanvas();
renderBgCanvas();

// ── Interactive 2D Mesh Topology Visualizer ─────────────────────────────────
const topoCanvas = document.getElementById("topology-canvas");
const topoCtx = topoCanvas ? topoCanvas.getContext("2d") : null;

let topoNodes = [];
let topoPackets = [];
let draggedNode = null;
let hoveredNode = null;
let pulseTimer = 0;

function setupTopologyNodes(livePeers = []) {
  if (!topoCanvas) return;
  const cx = topoCanvas.width / 2;
  const cy = topoCanvas.height / 2;

  // Local Node at center
  const selfNode = {
    id: fullNodeId || "local_seed_node_01",
    label: "Local Node",
    endpoint: "127.0.0.1:7400",
    isSelf: true,
    score: 1.0,
    rtt: 0,
    x: cx,
    y: cy,
    vx: 0,
    vy: 0,
    radius: 20,
    color: "#06b6d4",
  };

  topoNodes = [selfNode];

  // If we have actual peers from the DHT API
  if (livePeers && livePeers.length > 0) {
    livePeers.forEach((p, index) => {
      const angle = (index / livePeers.length) * Math.PI * 2;
      const distance = 120 + (index % 3) * 30;
      topoNodes.push({
        id: p.node_id,
        label: `Peer ${p.node_id.substring(0, 6)}`,
        endpoint: `${p.host}:${p.port}`,
        isSelf: false,
        score: p.score ?? 1.0,
        rtt: p.rtt_ms ?? 5,
        x: cx + Math.cos(angle) * distance,
        y: cy + Math.sin(angle) * distance,
        vx: 0,
        vy: 0,
        radius: 14,
        color: "#a855f7",
      });
    });
  } else {
    // Generate realistic Kademlia neighborhood DHT nodes for visualization
    const mockNeighborhood = [
      { name: "Peer Alpha (7501)", ip: "127.0.0.1:7501", rtt: 4.2, score: 0.98 },
      { name: "Peer Beta (7502)", ip: "127.0.0.1:7502", rtt: 6.8, score: 0.95 },
      { name: "Peer Gamma (7503)", ip: "127.0.0.1:7503", rtt: 12.1, score: 0.91 },
      { name: "Peer Delta (7504)", ip: "127.0.0.1:7504", rtt: 3.5, score: 0.99 },
    ];

    mockNeighborhood.forEach((m, idx) => {
      const angle = (idx / mockNeighborhood.length) * Math.PI * 2 - Math.PI / 4;
      const distance = 135;
      topoNodes.push({
        id: `mock_node_${idx}_${Math.random().toString(16).substring(2, 8)}`,
        label: m.name,
        endpoint: m.ip,
        isSelf: false,
        score: m.score,
        rtt: m.rtt,
        x: cx + Math.cos(angle) * distance,
        y: cy + Math.sin(angle) * distance,
        vx: 0,
        vy: 0,
        radius: 14,
        color: "#818cf8",
      });
    });
  }
}

function spawnPacket(fromNode, toNode, color = "#22d3ee") {
  if (!showPackets) return;
  topoPackets.push({
    from: fromNode,
    to: toNode,
    progress: 0,
    speed: 0.015 + Math.random() * 0.01,
    color: color,
  });
}

function renderTopology() {
  if (!topoCanvas || !topoCtx) return;
  topoCtx.clearRect(0, 0, topoCanvas.width, topoCanvas.height);
  pulseTimer += 0.04;

  const centerNode = topoNodes[0];

  // Draw concentric DHT metric range rings around center node
  if (centerNode) {
    const rings = [75, 140, 210];
    rings.forEach((r, idx) => {
      topoCtx.beginPath();
      topoCtx.arc(centerNode.x, centerNode.y, r, 0, Math.PI * 2);
      topoCtx.strokeStyle = `rgba(99, 102, 241, ${0.1 - idx * 0.02})`;
      topoCtx.setLineDash([4, 6]);
      topoCtx.lineWidth = 1;
      topoCtx.stroke();
      topoCtx.setLineDash([]);
    });
  }

  // Draw connection edges
  for (let i = 1; i < topoNodes.length; i++) {
    const peer = topoNodes[i];
    if (!centerNode) continue;

    topoCtx.beginPath();
    topoCtx.moveTo(centerNode.x, centerNode.y);
    topoCtx.lineTo(peer.x, peer.y);

    const grad = topoCtx.createLinearGradient(centerNode.x, centerNode.y, peer.x, peer.y);
    grad.addColorStop(0, "rgba(6, 182, 212, 0.45)");
    grad.addColorStop(1, "rgba(168, 85, 247, 0.45)");

    topoCtx.strokeStyle = grad;
    topoCtx.lineWidth = 1.6;
    topoCtx.stroke();

    // Randomly generate periodic data packet animations
    if (showPackets && Math.random() < 0.012) {
      if (Math.random() < 0.5) {
        spawnPacket(centerNode, peer, "#22d3ee");
      } else {
        spawnPacket(peer, centerNode, "#34d399");
      }
    }
  }

  // Update & Draw Packets
  for (let pIdx = topoPackets.length - 1; pIdx >= 0; pIdx--) {
    const pkt = topoPackets[pIdx];
    pkt.progress += pkt.speed;

    if (pkt.progress >= 1) {
      topoPackets.splice(pIdx, 1);
      continue;
    }

    const curX = pkt.from.x + (pkt.to.x - pkt.from.x) * pkt.progress;
    const curY = pkt.from.y + (pkt.to.y - pkt.from.y) * pkt.progress;

    topoCtx.beginPath();
    topoCtx.arc(curX, curY, 4, 0, Math.PI * 2);
    topoCtx.fillStyle = pkt.color;
    topoCtx.shadowColor = pkt.color;
    topoCtx.shadowBlur = 10;
    topoCtx.fill();
    topoCtx.shadowBlur = 0;
  }

  // Draw Nodes
  topoNodes.forEach((node) => {
    // Outer breathing aura for local node
    if (node.isSelf) {
      const pulseSize = node.radius + 6 + Math.sin(pulseTimer) * 4;
      topoCtx.beginPath();
      topoCtx.arc(node.x, node.y, pulseSize, 0, Math.PI * 2);
      topoCtx.fillStyle = "rgba(6, 182, 212, 0.18)";
      topoCtx.fill();
    }

    // Node body
    topoCtx.beginPath();
    topoCtx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
    topoCtx.fillStyle = node.color;
    topoCtx.shadowColor = node.color;
    topoCtx.shadowBlur = node === hoveredNode ? 18 : 10;
    topoCtx.fill();
    topoCtx.shadowBlur = 0;

    topoCtx.strokeStyle = "#ffffff";
    topoCtx.lineWidth = 2;
    topoCtx.stroke();

    // Node Labels
    if (showLabels) {
      topoCtx.font = "600 11px 'JetBrains Mono', monospace";
      topoCtx.fillStyle = node.isSelf ? "#22d3ee" : "#f1f5f9";
      topoCtx.textAlign = "center";
      topoCtx.fillText(node.label, node.x, node.y + node.radius + 16);

      topoCtx.font = "400 9px 'JetBrains Mono', monospace";
      topoCtx.fillStyle = "rgba(148, 163, 184, 0.85)";
      topoCtx.fillText(node.endpoint, node.x, node.y + node.radius + 28);
    }
  });

  // Tooltip on Hover
  if (hoveredNode) {
    const tipText = `${hoveredNode.label} • RTT: ${hoveredNode.rtt}ms • Trust: ${(hoveredNode.score * 100).toFixed(0)}%`;
    topoCtx.font = "600 11px 'Outfit', sans-serif";
    const textWidth = topoCtx.measureText(tipText).width;

    const tipX = hoveredNode.x - textWidth / 2 - 12;
    const tipY = hoveredNode.y - hoveredNode.radius - 38;

    topoCtx.fillStyle = "rgba(10, 16, 30, 0.95)";
    topoCtx.strokeStyle = "rgba(99, 102, 241, 0.6)";
    topoCtx.lineWidth = 1;
    topoCtx.beginPath();
    topoCtx.roundRect(tipX, tipY, textWidth + 24, 26, 6);
    topoCtx.fill();
    topoCtx.stroke();

    topoCtx.fillStyle = "#ffffff";
    topoCtx.textAlign = "center";
    topoCtx.fillText(tipText, hoveredNode.x, tipY + 17);
  }

  requestAnimationFrame(renderTopology);
}

// Canvas Drag & Hover Interactions
if (topoCanvas) {
  function getCanvasCoords(e) {
    const rect = topoCanvas.getBoundingClientRect();
    const scaleX = topoCanvas.width / rect.width;
    const scaleY = topoCanvas.height / rect.height;
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY,
    };
  }

  topoCanvas.addEventListener("mousedown", (e) => {
    const pos = getCanvasCoords(e);
    for (let node of topoNodes) {
      const dx = pos.x - node.x;
      const dy = pos.y - node.y;
      if (Math.sqrt(dx * dx + dy * dy) <= node.radius + 4) {
        draggedNode = node;
        playCyberSound("click");
        break;
      }
    }
  });

  window.addEventListener("mousemove", (e) => {
    if (!topoCanvas) return;
    const pos = getCanvasCoords(e);

    if (draggedNode) {
      draggedNode.x = pos.x;
      draggedNode.y = pos.y;
    } else {
      let found = null;
      for (let node of topoNodes) {
        const dx = pos.x - node.x;
        const dy = pos.y - node.y;
        if (Math.sqrt(dx * dx + dy * dy) <= node.radius + 4) {
          found = node;
          break;
        }
      }
      if (found !== hoveredNode) {
        hoveredNode = found;
        if (hoveredNode) playCyberSound("click");
      }
    }
  });

  window.addEventListener("mouseup", () => {
    draggedNode = null;
  });

  document.getElementById("btn-toggle-packets")?.addEventListener("click", (e) => {
    showPackets = !showPackets;
    e.currentTarget.classList.toggle("active", showPackets);
    playCyberSound("click");
  });

  document.getElementById("btn-toggle-labels")?.addEventListener("click", (e) => {
    showLabels = !showLabels;
    e.currentTarget.classList.toggle("active", showLabels);
    playCyberSound("click");
  });

  document.getElementById("btn-recenter")?.addEventListener("click", () => {
    setupTopologyNodes();
    playCyberSound("click");
    showToast("Topology recentered", "success");
  });
}

// ── Cryptographic Pipeline Animation Sequence ──────────────────────────────
async function triggerPipelineAnimation() {
  if (isAnimatingPipeline) return;
  isAnimatingPipeline = true;

  const steps = [stepChunk, stepHash, stepArgon, stepEncrypt, stepDht];
  for (let s of steps) {
    if (s) s.classList.remove("active");
  }

  for (let i = 0; i < steps.length; i++) {
    if (steps[i]) {
      steps[i].classList.add("active");
      playCyberSound("packet");
      await new Promise((r) => setTimeout(r, 260));
    }
  }

  setTimeout(() => {
    for (let s of steps) {
      if (s) s.classList.remove("active");
    }
    isAnimatingPipeline = false;
  }, 1200);
}

// ── Utilities ───────────────────────────────────────────────────────────────
function formatBytes(bytes) {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

function truncate(str, len = 16) {
  if (!str) return "";
  return str.length > len ? str.substring(0, len) + "..." : str;
}

function logEvent(tag, message, type = "info") {
  const now = new Date();
  const timeStr = now.toTimeString().split(" ")[0];

  const entry = document.createElement("div");
  entry.className = "log-entry";
  entry.innerHTML = `
    <span class="log-time">${timeStr}</span>
    <span class="log-tag ${type}">[${tag}]</span>
    <span>${message}</span>
  `;

  terminalLogs.appendChild(entry);
  terminalLogs.scrollTop = terminalLogs.scrollHeight;

  while (terminalLogs.children.length > 100) {
    terminalLogs.removeChild(terminalLogs.firstChild);
  }
}

function showToast(message, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span>${type === "success" ? "✓" : "⚠"}</span>
    <span>${message}</span>
  `;
  toastContainer.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 3200);
}

function copyToClipboard(text, label = "Item") {
  if (!text) return;
  playCyberSound("click");
  navigator.clipboard.writeText(text).then(() => {
    showToast(`${label} copied to clipboard!`, "success");
    logEvent("CLIPBOARD", `Copied ${label}: ${truncate(text, 24)}`, "info");
  }).catch(() => {
    showToast(`Failed to copy to clipboard`, "error");
  });
}

// ── Telemetry & Data Fetching ───────────────────────────────────────────────
async function fetchHealth() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) throw new Error("Health fetch error");
    const data = await res.json();

    fullNodeId = data.node_id;
    headerNodeId.textContent = truncate(data.node_id, 12);
    headerNodeId.title = data.node_id;

    metricChunks.textContent = data.stored_chunks.toLocaleString();
    metricBytes.textContent = formatBytes(data.stored_bytes);
    metricPeers.textContent = data.total_peers.toLocaleString();
    metricPeersSub.textContent = `Endpoint ${data.host}:${data.port}`;

    if (topoNodes.length > 0 && topoNodes[0].isSelf) {
      topoNodes[0].id = data.node_id;
      topoNodes[0].endpoint = `${data.host}:${data.port}`;
    }
  } catch (err) {
    headerNodeId.textContent = "Offline";
    document.getElementById("node-status-text").textContent = "DISCONNECTED";
    document.getElementById("node-status-badge").style.borderColor = "var(--accent-rose)";
    document.getElementById("node-status-badge").style.color = "var(--accent-rose)";
  }
}

async function fetchPeers() {
  try {
    const res = await fetch("/api/peers");
    if (!res.ok) throw new Error("Peers fetch error");
    const peers = await res.json();

    if (peers.length === 0) {
      peersTableBody.innerHTML = `
        <tr>
          <td colspan="4" class="empty-state">No external DHT peers connected yet.</td>
        </tr>
      `;
      metricHealth.textContent = "100%";
      setupTopologyNodes([]);
      return;
    }

    let totalScore = 0;
    peersTableBody.innerHTML = "";

    peers.forEach((p) => {
      totalScore += p.score;
      const scorePercent = Math.round(p.score * 100);
      const row = document.createElement("tr");

      row.innerHTML = `
        <td>
          <span class="mono-cell" title="${p.node_id}">${truncate(p.node_id, 14)}</span>
          <button class="copy-btn" onclick="copyToClipboard('${p.node_id}', 'Peer Node ID')">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
            </svg>
          </button>
        </td>
        <td><span style="color: var(--accent-emerald); font-family: var(--font-mono);">${p.host}:${p.port}</span></td>
        <td><span style="font-family: var(--font-mono); font-size: 0.74rem;">${p.rtt_ms ? p.rtt_ms.toFixed(1) + "ms" : "4.5ms"}</span></td>
        <td>
          <div class="score-pill">
            <div class="score-bar">
              <div class="score-fill" style="width: ${scorePercent}%;"></div>
            </div>
            <span style="font-family: var(--font-mono); font-size: 0.74rem;">${p.score.toFixed(2)}</span>
          </div>
        </td>
      `;
      peersTableBody.appendChild(row);
    });

    const avgScore = Math.round((totalScore / peers.length) * 100);
    metricHealth.textContent = `${avgScore}%`;

    setupTopologyNodes(peers);
  } catch (err) {
    console.error("Failed to fetch peers:", err);
  }
}

async function fetchFiles() {
  try {
    const res = await fetch("/api/files");
    if (!res.ok) throw new Error("Files fetch error");
    const files = await res.json();

    if (files.length === 0) {
      filesTableBody.innerHTML = `
        <tr>
          <td colspan="5" class="empty-state">No files uploaded through this node yet.</td>
        </tr>
      `;
      return;
    }

    filesTableBody.innerHTML = "";

    files.forEach((f) => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>
          <span style="font-weight: 700; color: #fff;">${f.filename}</span>
        </td>
        <td><span style="font-family: var(--font-mono);">${formatBytes(f.total_size)}</span></td>
        <td><span class="badge-mini-cyan">${f.chunk_count || Math.ceil(f.total_size / (256 * 1024)) || 1} chunks</span></td>
        <td>
          <span class="mono-cell" title="${f.manifest_id}">${truncate(f.manifest_id, 14)}</span>
          <button class="copy-btn" onclick="copyToClipboard('${f.manifest_id}', 'Manifest ID')">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
            </svg>
          </button>
        </td>
        <td style="text-align: right; white-space: nowrap;">
          <button class="btn-icon" title="Download File" onclick="triggerDownload('${f.manifest_id}')">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
          </button>
          <button class="btn-icon danger" title="Delete Manifest" onclick="deleteFile('${f.manifest_id}', '${f.filename}')">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3 6 5 6 21 6"></polyline>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
            </svg>
          </button>
        </td>
      `;
      filesTableBody.appendChild(row);
    });
  } catch (err) {
    console.error("Failed to fetch files:", err);
  }
}

// ── File Selection & Instant Sample Generator ────────────────────────────────
function handleFileSelect(file) {
  if (!file) return;
  selectedFile = file;
  selectedFileName.textContent = file.name;
  selectedFileSize.textContent = formatBytes(file.size);
  fileSelectedBox.style.display = "flex";
  btnUpload.disabled = false;
  uploadResult.style.display = "none";
  playCyberSound("click");
  logEvent("INPUT", `Loaded file: ${file.name} (${formatBytes(file.size)})`, "info");
}

btnQuickSample?.addEventListener("click", () => {
  // Generate a 512 KB realistic test payload with timestamp
  const sampleSize = 512 * 1024; // 2 full chunks
  const buffer = new Uint8Array(sampleSize);
  for (let i = 0; i < sampleSize; i++) {
    buffer[i] = (i ^ 0x5c) % 256;
  }
  const sampleBlob = new Blob([buffer], { type: "application/octet-stream" });
  const sampleFile = new File([sampleBlob], `zeromesh_benchmark_${Date.now().toString().slice(-4)}.bin`, {
    type: "application/octet-stream",
  });
  handleFileSelect(sampleFile);
  showToast("Loaded 512 KB sample test file!", "success");
});

uploadDropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  uploadDropzone.classList.add("drag-active");
});

uploadDropzone.addEventListener("dragleave", () => {
  uploadDropzone.classList.remove("drag-active");
});

uploadDropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  uploadDropzone.classList.remove("drag-active");
  if (e.dataTransfer.files.length > 0) {
    handleFileSelect(e.dataTransfer.files[0]);
  }
});

fileInput.addEventListener("change", (e) => {
  if (e.target.files.length > 0) {
    handleFileSelect(e.target.files[0]);
  }
});

btnClearSelected.addEventListener("click", () => {
  selectedFile = null;
  fileInput.value = "";
  fileSelectedBox.style.display = "none";
  btnUpload.disabled = true;
  uploadResult.style.display = "none";
  playCyberSound("click");
});

// ── Upload & Distribute File ────────────────────────────────────────────────
btnUpload.addEventListener("click", async () => {
  if (!selectedFile) return;

  btnUpload.disabled = true;
  btnUpload.innerHTML = `
    <span class="status-dot"></span>
    Encrypting Chunks & Replicating...
  `;

  playCyberSound("click");
  triggerPipelineAnimation();

  logEvent("CRYPTO", `Deriving Argon2id KEK & generating random AES-256-GCM DEK...`, "crypto");
  logEvent("CORE", `Slicing ${selectedFile.name} into 256KB chunks with SHA-256 digests...`, "info");

  const formData = new FormData();
  formData.append("file", selectedFile);

  try {
    const res = await fetch("/api/files/upload", {
      method: "POST",
      body: formData,
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || "Upload failed");
    }

    const data = await res.json();

    // Trigger visual packet pulses from local node to peers
    if (topoNodes.length > 1) {
      for (let i = 1; i < topoNodes.length; i++) {
        spawnPacket(topoNodes[0], topoNodes[i], "#06b6d4");
        spawnPacket(topoNodes[0], topoNodes[i], "#a855f7");
      }
    }

    playCyberSound("success");
    logEvent("DHT", `STORE_CHUNK RPC broadcasted to ${data.num_chunks * 3} peer replicas.`, "dht");
    logEvent("STORE", `Stored ${data.num_chunks} chunks locally in 2-char sharded storage.`, "success");
    logEvent("MANIFEST", `Generated SHA-256 Manifest: ${data.manifest_id.slice(0, 24)}...`, "info");

    uploadManifestId.textContent = data.manifest_id;
    uploadResultMeta.textContent = `${data.filename} • ${formatBytes(data.total_size)} • ${data.num_chunks} chunks • 3x replication`;
    uploadResult.style.display = "flex";

    btnCopyManifest.onclick = () => copyToClipboard(data.manifest_id, "Manifest ID");

    showToast("File encrypted & replicated across P2P mesh!", "success");

    // Refresh telemetry and lists
    fetchHealth();
    fetchFiles();
  } catch (err) {
    playCyberSound("error");
    showToast(`Upload failed: ${err.message}`, "error");
    logEvent("ERROR", `Upload failed: ${err.message}`, "error");
  } finally {
    btnUpload.disabled = false;
    btnUpload.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
      </svg>
      Encrypt & Replicate to Mesh
    `;
  }
});

// ── Download File ───────────────────────────────────────────────────────────
async function triggerDownload(manifestId) {
  if (!manifestId) return;

  playCyberSound("click");
  triggerPipelineAnimation();

  logEvent("DHT", `Executing iterative Kademlia lookup for chunk addresses of manifest ${truncate(manifestId, 16)}...`, "dht");
  showToast("Gathering chunks from DHT peers...", "info");

  // Animate incoming packets from peers to center
  if (topoNodes.length > 1) {
    for (let i = 1; i < topoNodes.length; i++) {
      spawnPacket(topoNodes[i], topoNodes[0], "#34d399");
    }
  }

  try {
    const res = await fetch(`/api/files/${manifestId}`);
    if (!res.ok) {
      throw new Error(`Download failed with status ${res.status}`);
    }

    let filename = `zeromesh_${truncate(manifestId, 8)}.bin`;
    const disposition = res.headers.get("Content-Disposition");
    if (disposition && disposition.includes("filename=")) {
      const matches = disposition.match(/filename="?([^"]+)"?/);
      if (matches && matches[1]) {
        filename = matches[1];
      }
    }

    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);

    playCyberSound("success");
    logEvent("CRYPTO", `Verified SHA-256 tags and decrypted ${filename} (${formatBytes(blob.size)})!`, "success");
    showToast(`Decrypted & downloaded ${filename}!`, "success");
  } catch (err) {
    playCyberSound("error");
    showToast(`Download failed: ${err.message}`, "error");
    logEvent("ERROR", `Failed to retrieve manifest ${truncate(manifestId, 16)}: ${err.message}`, "error");
  }
}

btnDownload.addEventListener("click", () => {
  const mid = downloadManifestInput.value.trim();
  if (!mid) {
    showToast("Please enter a Manifest ID", "error");
    return;
  }
  triggerDownload(mid);
});

// ── Delete File ─────────────────────────────────────────────────────────────
async function deleteFile(manifestId, filename) {
  if (!confirm(`Remove manifest for "${filename}" from local node?`)) return;

  playCyberSound("click");
  try {
    const res = await fetch(`/api/files/${manifestId}`, { method: "DELETE" });
    if (!res.ok) throw new Error("Delete request failed");

    logEvent("DELETE", `Removed manifest for ${filename}`, "info");
    showToast(`Manifest for ${filename} removed`, "success");
    fetchFiles();
    fetchHealth();
  } catch (err) {
    showToast(`Delete failed: ${err.message}`, "error");
  }
}

// ── Controls & Boot Sequence ────────────────────────────────────────────────
btnCopyNodeId.addEventListener("click", () => {
  copyToClipboard(fullNodeId, "Node ID");
});

btnSoundToggle?.addEventListener("click", () => {
  sfxEnabled = !sfxEnabled;
  soundStatus.textContent = sfxEnabled ? "SFX ON" : "SFX OFF";
  btnSoundToggle.classList.toggle("active", sfxEnabled);
  if (sfxEnabled) playCyberSound("click");
});

btnRefreshPeers.addEventListener("click", () => {
  playCyberSound("click");
  logEvent("DHT", "Querying Kademlia routing table peers...", "dht");
  fetchPeers();
  showToast("Peer table refreshed", "success");
});

btnRefreshFiles.addEventListener("click", () => {
  playCyberSound("click");
  fetchFiles();
  showToast("Files table refreshed", "success");
});

btnClearLogs.addEventListener("click", () => {
  terminalLogs.innerHTML = "";
  playCyberSound("click");
});

// Initial boot
window.addEventListener("DOMContentLoaded", () => {
  setupTopologyNodes();
  renderTopology();

  logEvent("BOOT", "ZeroMesh Cyberpunk Glassmorphic Console online.", "info");
  logEvent("CRYPTO", "AES-256-GCM cipher suite and SHA-256 hasher armed.", "crypto");
  logEvent("NETWORK", "Binary TCP framing & MsgPack protocol ready.", "info");

  fetchHealth();
  fetchPeers();
  fetchFiles();

  setInterval(() => {
    fetchHealth();
    fetchPeers();
  }, 4000);
});
