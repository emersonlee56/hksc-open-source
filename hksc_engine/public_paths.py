"""Portable paths for an explicitly supplied public universe manifest."""
from pathlib import Path
import hashlib


def resolve_source_path(manifest_file, value):
    relative = Path(value)
    if relative.is_absolute() or '..' in relative.parts or '\\' in value:
        raise ValueError('Universe source must be a contained relative path')
    base = Path(manifest_file).resolve().parent
    result = (base / relative).resolve()
    if not result.is_relative_to(base) or result.is_symlink():
        raise ValueError('Universe source escaped its manifest directory')
    return result


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
