/**
 * ZeroMesh Web Dashboard — Client Logic
 * =====================================
 * Handles real-time polling, drag-and-drop file uploads,
 * parallel P2P download triggering, peer telemetry, and terminal logging.
 */

// ── State ───────────────────────────────────────────────────────────────────
let fullNodeId = "";
let selectedFile = null;

// ── DOM References ──────────────────────────────────────────────────────────
const headerNodeId = document.getElementById("header-node-id");
const btnCopyNodeId = document.getElementById("btn-copy-node-id");

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

// ── Utilities ───────────────────────────────────────────────────────────────
function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
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

  // Keep max 100 entries
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
          <td colspan="3" class="empty-state">No external DHT peers connected yet.</td>
        </tr>
      `;
      metricHealth.textContent = "100%";
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
        <td><span style="color: var(--accent-emerald);">${p.host}:${p.port}</span></td>
        <td>
          <div class="score-pill">
            <div class="score-bar">
              <div class="score-fill" style="width: ${scorePercent}%;"></div>
            </div>
            <span>${p.score.toFixed(3)}</span>
          </div>
        </td>
      `;
      peersTableBody.appendChild(row);
    });

    const avgScore = Math.round((totalScore / peers.length) * 100);
    metricHealth.textContent = `${avgScore}%`;
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
          <td colspan="4" class="empty-state">No files uploaded through this node yet.</td>
        </tr>
      `;
      return;
    }

    filesTableBody.innerHTML = "";

    files.forEach((f) => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>
          <span style="font-weight: 600; color: #fff;">${f.filename}</span>
        </td>
        <td>${formatBytes(f.total_size)}</td>
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
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
          </button>
          <button class="btn-icon danger" title="Delete Manifest" onclick="deleteFile('${f.manifest_id}', '${f.filename}')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
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

// ── File Upload Flow ────────────────────────────────────────────────────────
function handleFileSelect(file) {
  if (!file) return;
  selectedFile = file;
  selectedFileName.textContent = file.name;
  selectedFileSize.textContent = formatBytes(file.size);
  fileSelectedBox.style.display = "flex";
  btnUpload.disabled = false;
  uploadResult.style.display = "none";
  logEvent("INPUT", `Selected file: ${file.name} (${formatBytes(file.size)})`, "info");
}

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
});

btnUpload.addEventListener("click", async () => {
  if (!selectedFile) return;

  btnUpload.disabled = true;
  btnUpload.innerHTML = `
    <span class="status-dot"></span>
    Encrypting & Chunking...
  `;

  logEvent("CRYPTO", `Generating AES-256-GCM cipher & 256KB chunks for ${selectedFile.name}...`, "crypto");

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

    logEvent("STORE", `Stored ${data.num_chunks} chunks with 3x replication factor.`, "success");
    logEvent("MANIFEST", `Generated SHA-256 Manifest: ${data.manifest_id.slice(0, 20)}...`, "info");

    uploadManifestId.textContent = data.manifest_id;
    uploadResultMeta.textContent = `${data.filename} • ${formatBytes(data.total_size)} • ${data.num_chunks} chunks`;
    uploadResult.style.display = "flex";

    btnCopyManifest.onclick = () => copyToClipboard(data.manifest_id, "Manifest ID");

    showToast("File uploaded and encrypted across mesh!", "success");

    // Refresh telemetry and lists
    fetchHealth();
    fetchFiles();
  } catch (err) {
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

// ── File Download Flow ──────────────────────────────────────────────────────
async function triggerDownload(manifestId) {
  if (!manifestId) return;

  logEvent("DHT", `Initiating parallel GET_CHUNK RPC lookups for manifest ${truncate(manifestId, 16)}...`, "dht");
  showToast("Gathering chunks from DHT peers...", "info");

  try {
    const res = await fetch(`/api/files/${manifestId}`);
    if (!res.ok) {
      throw new Error(`Download failed with status ${res.status}`);
    }

    // Extract filename from Content-Disposition header if available
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

    logEvent("CRYPTO", `Verified SHA-256 and decrypted ${filename} (${formatBytes(blob.size)}) successfully!`, "success");
    showToast(`Downloaded & decrypted ${filename}!`, "success");
  } catch (err) {
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

// ── Delete File Flow ────────────────────────────────────────────────────────
async function deleteFile(manifestId, filename) {
  if (!confirm(`Remove manifest for "${filename}" from local node?`)) return;

  try {
    const res = await fetch(`/api/files/${manifestId}`, { method: "DELETE" });
    if (!res.ok) throw new Error("Delete request failed");

    logEvent("DELETE", `Removed manifest for ${filename}`, "info");
    showToast(`Manifest for ${filename} removed`, "success");
    fetchFiles();
  } catch (err) {
    showToast(`Delete failed: ${err.message}`, "error");
  }
}

// ── Event Handlers & Polling ────────────────────────────────────────────────
btnCopyNodeId.addEventListener("click", () => {
  copyToClipboard(fullNodeId, "Node ID");
});

btnRefreshPeers.addEventListener("click", () => {
  logEvent("DHT", "Refreshing Kademlia routing table peers...", "dht");
  fetchPeers();
  showToast("Peer table refreshed", "success");
});

btnRefreshFiles.addEventListener("click", () => {
  fetchFiles();
  showToast("Files table refreshed", "success");
});

btnClearLogs.addEventListener("click", () => {
  terminalLogs.innerHTML = "";
});

// Initial boot sequence
window.addEventListener("DOMContentLoaded", () => {
  logEvent("BOOT", "ZeroMesh Web Console initialized.", "info");
  logEvent("CRYPTO", "AES-256-GCM cipher suite and SHA-256 hasher armed.", "crypto");
  logEvent("NETWORK", "Binary TCP framing & MsgPack protocol ready.", "info");

  fetchHealth();
  fetchPeers();
  fetchFiles();

  // Periodic polling every 5 seconds
  setInterval(() => {
    fetchHealth();
    fetchPeers();
  }, 5000);
});
