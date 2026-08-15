"""Checksum helpers for reproducible model and artifact references."""

from pathlib import Path


def sha256_file(path: Path) -> str:
    """Return the lowercase SHA-256 digest for a file."""

    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
