from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlparse
from uuid import uuid4

import fsspec


@dataclass(frozen=True)
class PutResult:
    url: str
    sha256: str
    size_bytes: int | None = None


class ArtifactStore:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _join(self, *parts: str) -> str:
        return "/".join([self.base_url, *[p.strip("/") for p in parts]])

    def _is_absolute_target(self, target: str) -> bool:
        parsed = urlparse(target)
        if parsed.scheme != "":
            return True
        return os.path.isabs(target)

    def _looks_like_file_target(self, target: str) -> bool:
        if target.endswith("/"):
            return False
        parsed = urlparse(target)
        path = parsed.path if parsed.scheme != "" else target
        tail = path.rstrip("/").split("/")[-1]
        return "." in tail and tail not in (".", "..")

    def _resolve_url(self, y: str, z: str | None, *, source: Any) -> str:
        base = y if self._is_absolute_target(y) else self._join(y)

        if y.endswith("/"):
            is_dir = True
        elif not self._is_absolute_target(y):
            is_dir = not self._looks_like_file_target(y)
        else:
            parsed = urlparse(y)
            if parsed.scheme in ("", "file"):
                try:
                    local = self._local_path(base)
                    if local.exists():
                        is_dir = local.is_dir()
                    else:
                        is_dir = not self._looks_like_file_target(y)
                except Exception:
                    is_dir = not self._looks_like_file_target(y)
            else:
                is_dir = not self._looks_like_file_target(y)

        if z is not None and not self._looks_like_file_target(base):
            is_dir = True

        if not is_dir:
            return base

        filename: str
        if z is not None and z.strip("/"):
            filename = z.strip("/")
        else:
            if isinstance(source, (str, os.PathLike)) and Path(source).exists():
                filename = Path(source).name
            elif isinstance(source, (dict, list)):
                filename = f"{uuid4().hex}.json"
            elif isinstance(source, (bytes, bytearray, memoryview)):
                filename = f"{uuid4().hex}.bin"
            else:
                filename = f"{uuid4().hex}.txt"

        return base.rstrip("/") + "/" + filename

    def _put_bytes_to_url(self, url: str, data: bytes) -> PutResult:
        sha256 = hashlib.sha256(data).hexdigest()

        parsed = urlparse(url)
        if parsed.scheme in ("", "file"):
            self._put_bytes_local(url, data)
        else:
            # MVP: no atomic guarantee for object stores
            with fsspec.open(url, "wb") as f:
                f.write(data)

        return PutResult(url=url, sha256=sha256, size_bytes=len(data))

    def _put_file_to_url(self, url: str, local_path: str) -> PutResult:
        parsed = urlparse(url)

        h = hashlib.sha256()
        size = 0
        with open(local_path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
                size += len(chunk)
        sha256 = h.hexdigest()

        if parsed.scheme in ("", "file"):
            self._put_file_local(url, local_path)
        else:
            fs, _, paths = fsspec.get_fs_token_paths(url)
            fs.put(local_path, paths[0])

        return PutResult(url=url, sha256=sha256, size_bytes=size)

    def put(
        self,
        x: str | os.PathLike[str],
        y: str,
        z: str | None = None,
    ) -> PutResult:
        """Unified put API.

        Args:
            x: Local file path to store.
            y: Target path or file. Relative targets are joined with base_url.
                Can point to a directory or a file.
            z: Optional filename when y points to a directory.
        """

        x_path = Path(x)
        if not x_path.exists() or not x_path.is_file():
            raise FileNotFoundError(f"x must be an existing local file path: {x_path}")

        url = self._resolve_url(y, z, source=str(x_path))

        # Security: prevent directory traversal when writing under a local base_url.
        # Only applies to relative targets (joined under base_url). Absolute targets
        # are treated as explicit opt-out.
        if (not self._is_absolute_target(y)):
            parsed = urlparse(url)
            if parsed.scheme in ("", "file"):
                base_root = self._local_path(self.base_url)
                dst = self._local_path(url)

                try:
                    base_resolved = base_root.resolve(strict=False)
                    dst_resolved = dst.resolve(strict=False)
                    if not dst_resolved.is_relative_to(base_resolved):
                        raise ValueError("directory traversal detected in target path")
                except AttributeError:
                    # Fallback for older Python without Path.is_relative_to
                    base_resolved = os.path.realpath(str(base_root))
                    dst_resolved = os.path.realpath(str(dst))
                    if os.path.commonpath([dst_resolved, base_resolved]) != base_resolved:
                        raise ValueError("directory traversal detected in target path")

        # If y targets a file (not a directory), enforce extension match.
        y_is_dir = y.endswith("/")
        if not y_is_dir and self._looks_like_file_target(y):
            src_suffix = x_path.suffix
            parsed = urlparse(url)
            dst_path = parsed.path if parsed.scheme != "" else url
            dst_suffix = Path(dst_path).suffix
            if src_suffix != dst_suffix:
                raise ValueError(
                    f"File extension mismatch: x={src_suffix!r} vs y={dst_suffix!r}. "
                    "When y points to a file, x and y must have the same suffix."
                )

        return self._put_file_to_url(url, str(x_path))

    def open(self, url: str, mode: str = "rb") -> BinaryIO:
        return fsspec.open(url, mode).open()

    def _local_path(self, url: str) -> Path:
        parsed = urlparse(url)
        if parsed.scheme == "file":
            return Path(parsed.path)
        return Path(url)

    def _put_bytes_local(self, url: str, data: bytes) -> None:
        dst = self._local_path(url)
        dst.parent.mkdir(parents=True, exist_ok=True)

        tmp = dst.with_name(dst.name + f".tmp.{os.getpid()}")
        with tmp.open("wb") as f:
            f.write(data)
        os.replace(tmp, dst)

    def _put_file_local(self, url: str, local_path: str) -> None:
        import shutil

        dst = self._local_path(url)
        dst.parent.mkdir(parents=True, exist_ok=True)

        tmp = dst.with_name(dst.name + f".tmp.{os.getpid()}")
        shutil.copyfile(local_path, tmp)
        os.replace(tmp, dst)
