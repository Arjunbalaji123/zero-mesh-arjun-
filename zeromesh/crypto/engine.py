"""
ZeroMesh Crypto Engine
======================
Provides:
  - SHA-256 content hashing
  - AES-256-GCM authenticated encryption / decryption
  - Key derivation from a passphrase (PBKDF2-HMAC-SHA256)
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# ─── Constants ────────────────────────────────────────────────────────────────

KEY_SIZE_BYTES = 32          # 256-bit AES key
NONCE_SIZE_BYTES = 12        # 96-bit nonce (GCM standard recommendation)
SALT_SIZE_BYTES = 32         # Salt for PBKDF2
PBKDF2_ITERATIONS = 600_000  # OWASP 2023 recommendation for PBKDF2-HMAC-SHA256


# ─── Data Structures ──────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class EncryptedChunk:
    """
    An encrypted chunk ready for network transmission or storage.

    Attributes:
        nonce:      12-byte unique nonce used during encryption (send alongside ciphertext)
        ciphertext: AES-256-GCM ciphertext + 16-byte authentication tag (appended by AESGCM)
        content_id: SHA-256 hex digest of the **plaintext** chunk (used as DHT key)
    """
    nonce: bytes
    ciphertext: bytes
    content_id: str   # SHA-256 hex of the original plaintext chunk


# ─── Hashing ──────────────────────────────────────────────────────────────────

def sha256_hash(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def verify_hash(data: bytes, expected_hex: str) -> bool:
    """
    Constant-time comparison of ``sha256_hash(data)`` with ``expected_hex``.
    Uses ``hmac.compare_digest`` to prevent timing-oracle attacks.
    """
    actual = sha256_hash(data)
    return hmac.compare_digest(actual.encode(), expected_hex.encode())


# ─── Key Material ─────────────────────────────────────────────────────────────

def generate_key() -> bytes:
    """Generate a cryptographically random 256-bit AES key."""
    return secrets.token_bytes(KEY_SIZE_BYTES)


def derive_key(passphrase: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    """
    Derive a 256-bit key from a passphrase using PBKDF2-HMAC-SHA256.

    Returns:
        (key_bytes, salt_bytes) — store the salt alongside the encrypted data.
    """
    if salt is None:
        salt = secrets.token_bytes(SALT_SIZE_BYTES)

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_SIZE_BYTES,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    key = kdf.derive(passphrase.encode("utf-8"))
    return key, salt


# ─── Encryption ───────────────────────────────────────────────────────────────

def encrypt_chunk(plaintext: bytes, key: bytes) -> EncryptedChunk:
    """
    Encrypt a chunk using AES-256-GCM.

    Security properties:
      - Confidentiality: data is indistinguishable from random.
      - Integrity / Authentication: the GCM tag (last 16 bytes of ciphertext)
        detects any bit-level tampering during transit or storage.
      - A fresh random nonce is generated per chunk so the same plaintext
        always produces a different ciphertext (semantic security).

    Args:
        plaintext: Raw chunk bytes to encrypt.
        key:       32-byte (256-bit) AES key.

    Returns:
        EncryptedChunk with nonce, ciphertext+tag, and SHA-256 content ID.

    Raises:
        ValueError: if key is not exactly 32 bytes.
    """
    if len(key) != KEY_SIZE_BYTES:
        raise ValueError(f"Key must be {KEY_SIZE_BYTES} bytes, got {len(key)}")

    content_id = sha256_hash(plaintext)
    nonce = secrets.token_bytes(NONCE_SIZE_BYTES)

    aesgcm = AESGCM(key)
    # AESGCM.encrypt returns ciphertext || tag (tag is the last 16 bytes)
    ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data=None)

    return EncryptedChunk(
        nonce=nonce,
        ciphertext=ciphertext,
        content_id=content_id,
    )


def decrypt_chunk(encrypted: EncryptedChunk, key: bytes) -> bytes:
    """
    Decrypt an EncryptedChunk and verify its SHA-256 content ID.

    Args:
        encrypted: The EncryptedChunk to decrypt.
        key:       The 32-byte AES key used for encryption.

    Returns:
        The original plaintext bytes.

    Raises:
        cryptography.exceptions.InvalidTag: if GCM authentication fails
            (ciphertext was tampered with or key is wrong).
        ValueError: if the decrypted content's SHA-256 doesn't match the
            stored content ID (belt-and-suspenders integrity check).
    """
    if len(key) != KEY_SIZE_BYTES:
        raise ValueError(f"Key must be {KEY_SIZE_BYTES} bytes, got {len(key)}")

    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(encrypted.nonce, encrypted.ciphertext, associated_data=None)

    if not verify_hash(plaintext, encrypted.content_id):
        raise ValueError(
            f"Content ID mismatch after decryption! "
            f"Expected {encrypted.content_id}, got {sha256_hash(plaintext)}"
        )

    return plaintext
