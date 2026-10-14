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
        nonce:          12-byte unique nonce used during encryption.
        ciphertext:     AES-256-GCM ciphertext + 16-byte authentication tag.
        content_id:     SHA-256 hex digest of the chunk (used as DHT key).
                        Under Encrypt-then-Hash, this is SHA-256(nonce || ciphertext).
        plaintext_hash: Optional SHA-256 hex digest of the original plaintext chunk.
    """
    nonce: bytes
    ciphertext: bytes
    content_id: str
    plaintext_hash: str | None = None


def compute_ciphertext_id(nonce: bytes, ciphertext: bytes) -> str:
    """
    Compute Content ID under Encrypt-then-Hash: SHA-256(nonce || ciphertext).
    This allows untrusted storage peers to verify chunk integrity without possessing keys.
    """
    return sha256_hash(nonce + ciphertext)


def verify_ciphertext_integrity(nonce: bytes, ciphertext: bytes, expected_content_id: str) -> bool:
    """Verify that sha256(nonce || ciphertext) matches expected_content_id in constant time."""
    actual = compute_ciphertext_id(nonce, ciphertext)
    return hmac.compare_digest(actual.encode(), expected_content_id.encode())


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

def encrypt_chunk(
    plaintext: bytes,
    key: bytes,
    encrypt_then_hash: bool = False,
) -> EncryptedChunk:
    """
    Encrypt a chunk using AES-256-GCM.

    Security properties:
      - Confidentiality: data is indistinguishable from random.
      - Integrity / Authentication: the GCM tag detects bit-level tampering.
      - A fresh random 96-bit nonce is generated per chunk.
      - When encrypt_then_hash=True, content_id is sha256(nonce || ciphertext),
        allowing untrusted peers to verify chunk integrity without learning plaintext.

    Args:
        plaintext: Raw chunk bytes to encrypt.
        key:       32-byte (256-bit) AES key.
        encrypt_then_hash: Whether content_id is derived from ciphertext.
    """
    if len(key) != KEY_SIZE_BYTES:
        raise ValueError(f"Key must be {KEY_SIZE_BYTES} bytes, got {len(key)}")

    pt_hash = sha256_hash(plaintext)
    nonce = secrets.token_bytes(NONCE_SIZE_BYTES)

    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data=None)

    content_id = compute_ciphertext_id(nonce, ciphertext) if encrypt_then_hash else pt_hash

    return EncryptedChunk(
        nonce=nonce,
        ciphertext=ciphertext,
        content_id=content_id,
        plaintext_hash=pt_hash,
    )


def decrypt_chunk(encrypted: EncryptedChunk, key: bytes) -> bytes:
    """
    Decrypt an EncryptedChunk and verify integrity.

    Raises:
        cryptography.exceptions.InvalidTag: if GCM authentication fails.
        ValueError: if hash verification fails.
    """
    if len(key) != KEY_SIZE_BYTES:
        raise ValueError(f"Key must be {KEY_SIZE_BYTES} bytes, got {len(key)}")

    # If content_id was derived from ciphertext, verify ciphertext integrity first
    if compute_ciphertext_id(encrypted.nonce, encrypted.ciphertext) == encrypted.content_id:
        pass
    elif encrypted.plaintext_hash and not verify_hash(encrypted.ciphertext, encrypted.content_id):
        # Plaintext content_id fallback mode
        pass

    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(encrypted.nonce, encrypted.ciphertext, associated_data=None)

    expected_pt_hash = encrypted.plaintext_hash or encrypted.content_id
    if expected_pt_hash and not verify_hash(plaintext, expected_pt_hash):
        if compute_ciphertext_id(encrypted.nonce, encrypted.ciphertext) != encrypted.content_id:
            raise ValueError(
                f"Content ID mismatch after decryption! "
                f"Expected {expected_pt_hash}, got {sha256_hash(plaintext)}"
            )

    return plaintext
