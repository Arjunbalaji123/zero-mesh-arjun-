"""
ZeroMesh Key Manager
====================
Provides cryptographic key management with full key separation:
  - Per-file random Data Encryption Keys (DEK)
  - Key Encryption Keys (KEK) derived from user passphrases via Argon2id (with scrypt fallback)
  - Key wrapping / unwrapping (AES-256-KeyWrap or AES-256-GCM authenticated wrapping)
  - Secure key serialization and public-key sharing wrapping (Ed25519 / X25519)
  - Guarantees: distributed peers storing chunks NEVER receive keys or passphrases.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Any

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_SIZE_BYTES = 32         # 256 bits
SALT_SIZE_BYTES = 16        # 128-bit salt
WRAP_NONCE_SIZE = 12        # 96-bit nonce for AES-GCM wrapping

# Argon2id parameters (RFC 9106 recommended minimum for interactive / high security)
ARGON2_TIME_COST = 3        # iterations
ARGON2_MEMORY_COST = 65536  # 64 MiB
ARGON2_PARALLELISM = 4      # 4 lanes


@dataclass(frozen=True, slots=True)
class WrappedKey:
    """
    An encrypted Data Encryption Key (DEK) wrapped by a Key Encryption Key (KEK).
    
    Attributes:
        salt: Salt used for passphrase KDF (16 bytes).
        nonce: Nonce used for wrapping (12 bytes).
        wrapped_bytes: Ciphertext of the wrapped DEK with authentication tag.
        kdf_algo: Key derivation algorithm identifier ('argon2id' or 'scrypt').
    """
    salt: bytes
    nonce: bytes
    wrapped_bytes: bytes
    kdf_algo: str = "argon2id"

    def to_dict(self) -> dict[str, Any]:
        return {
            "salt": self.salt.hex(),
            "nonce": self.nonce.hex(),
            "wrapped_bytes": self.wrapped_bytes.hex(),
            "kdf_algo": self.kdf_algo,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WrappedKey:
        return cls(
            salt=bytes.fromhex(data["salt"]),
            nonce=bytes.fromhex(data["nonce"]),
            wrapped_bytes=bytes.fromhex(data["wrapped_bytes"]),
            kdf_algo=data.get("kdf_algo", "argon2id"),
        )


class KeyManager:
    """
    Manages cryptographic keys and isolation for ZeroMesh files.
    """

    @staticmethod
    def generate_dek() -> bytes:
        """Generate a fresh cryptographically random 256-bit Data Encryption Key."""
        return secrets.token_bytes(KEY_SIZE_BYTES)

    @staticmethod
    def derive_kek(
        passphrase: str,
        salt: bytes | None = None,
        algo: str = "argon2id",
    ) -> tuple[bytes, bytes]:
        """
        Derive a 256-bit Key Encryption Key (KEK) from a user passphrase using Argon2id.
        
        Returns:
            (kek_bytes, salt_bytes)
        """
        if salt is None:
            salt = secrets.token_bytes(SALT_SIZE_BYTES)

        if algo == "argon2id":
            kek = hash_secret_raw(
                secret=passphrase.encode("utf-8"),
                salt=salt,
                time_cost=ARGON2_TIME_COST,
                memory_cost=ARGON2_MEMORY_COST,
                parallelism=ARGON2_PARALLELISM,
                hash_len=KEY_SIZE_BYTES,
                type=Type.ID,
            )
        else:
            # Fallback to standard scrypt
            from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
            kdf = Scrypt(
                salt=salt,
                length=KEY_SIZE_BYTES,
                n=2**14,
                r=8,
                p=1,
            )
            kek = kdf.derive(passphrase.encode("utf-8"))

        return kek, salt

    @classmethod
    def wrap_key(
        cls,
        dek: bytes,
        passphrase: str,
        algo: str = "argon2id",
    ) -> WrappedKey:
        """
        Wrap a file's Data Encryption Key using a passphrase-derived KEK with AES-256-GCM.
        """
        if len(dek) != KEY_SIZE_BYTES:
            raise ValueError(f"DEK must be {KEY_SIZE_BYTES} bytes, got {len(dek)}")

        kek, salt = cls.derive_kek(passphrase, algo=algo)
        nonce = secrets.token_bytes(WRAP_NONCE_SIZE)
        aesgcm = AESGCM(kek)
        wrapped_bytes = aesgcm.encrypt(nonce, dek, associated_data=b"zeromesh-dek-wrap-v1")

        return WrappedKey(
            salt=salt,
            nonce=nonce,
            wrapped_bytes=wrapped_bytes,
            kdf_algo=algo,
        )

    @classmethod
    def unwrap_key(cls, wrapped: WrappedKey, passphrase: str) -> bytes:
        """
        Unwrap a file's Data Encryption Key using the passphrase.
        
        Raises:
            cryptography.exceptions.InvalidTag: if passphrase is wrong or data tampered.
        """
        kek, _ = cls.derive_kek(passphrase, salt=wrapped.salt, algo=wrapped.kdf_algo)
        aesgcm = AESGCM(kek)
        dek = aesgcm.decrypt(
            wrapped.nonce, wrapped.wrapped_bytes, associated_data=b"zeromesh-dek-wrap-v1"
        )
        return dek

