"""Content storage. Graph state only ever holds BlobRefs (gs:// URIs), never the text itself.

Objects are content-addressed (sha256 in the name), so a node that is retried and produces different
LLM output writes a new object instead of clobbering or failing a precondition. Orphans are removed by
the bucket lifecycle rule and the cleanup job."""

import asyncio
import hashlib
import json
from collections import OrderedDict
from typing import Any, Protocol, TypedDict


class BlobRef(TypedDict):
    uri: str
    sha256: str
    size: int


class BlobStore(Protocol):
    async def put_text(self, path: str, text: str, content_type: str = "text/markdown") -> BlobRef: ...
    async def get_text(self, uri: str) -> str: ...
    async def exists(self, path: str) -> bool: ...
    async def delete_prefix(self, prefix: str) -> int: ...


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def job_path(user_id: str, job_id: str, kind: str, name: str, text: str, ext: str = "md") -> str:
    """users/{uid}/jobs/{job}/{kind}/{name}-{sha12}.{ext}"""
    return f"users/{user_id}/jobs/{job_id}/{kind}/{name}-{sha256(text)[:12]}.{ext}"


def job_prefix(user_id: str, job_id: str) -> str:
    return f"users/{user_id}/jobs/{job_id}/"


class GcsBlobStore:
    """google-cloud-storage is blocking, so every call runs in a worker thread. Uses ADC."""

    def __init__(self, bucket: str, project: str | None = None):
        from google.cloud import storage

        self._client = storage.Client(project=project or None)
        self._bucket = self._client.bucket(bucket)
        self.bucket_name = bucket

    def _uri(self, path: str) -> str:
        return f"gs://{self.bucket_name}/{path}"

    def _path(self, uri: str) -> str:
        prefix = f"gs://{self.bucket_name}/"
        if not uri.startswith(prefix):
            raise ValueError(f"URI {uri!r} is not in bucket {self.bucket_name}")
        return uri[len(prefix):]

    async def put_text(self, path: str, text: str, content_type: str = "text/markdown") -> BlobRef:
        data = text.encode("utf-8")

        def _put() -> None:
            blob = self._bucket.blob(path)
            blob.upload_from_string(data, content_type=f"{content_type}; charset=utf-8")

        await asyncio.to_thread(_put)
        return {"uri": self._uri(path), "sha256": sha256(text), "size": len(data)}

    async def get_text(self, uri: str) -> str:
        path = self._path(uri)
        return await asyncio.to_thread(lambda: self._bucket.blob(path).download_as_bytes().decode("utf-8"))

    async def exists(self, path: str) -> bool:
        return await asyncio.to_thread(lambda: self._bucket.blob(path).exists())

    async def delete_prefix(self, prefix: str) -> int:
        def _delete() -> int:
            blobs = list(self._client.list_blobs(self._bucket, prefix=prefix))
            for b in blobs:
                b.delete()
            return len(blobs)

        return await asyncio.to_thread(_delete)


class LocalBlobStore:
    """Filesystem store for offline local development (ENV=local only). URIs keep the gs:// shape."""

    def __init__(self, root: str, bucket: str = "local"):
        from pathlib import Path

        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.bucket_name = bucket

    def _file(self, path: str):
        f = (self.root / path).resolve()
        if not f.is_relative_to(self.root):
            raise ValueError("path escapes the blob root")
        return f

    async def put_text(self, path: str, text: str, content_type: str = "text/markdown") -> BlobRef:
        f = self._file(path)

        def _write() -> None:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")

        await asyncio.to_thread(_write)
        return {"uri": f"gs://{self.bucket_name}/{path}", "sha256": sha256(text), "size": len(text.encode())}

    async def get_text(self, uri: str) -> str:
        f = self._file(uri.removeprefix(f"gs://{self.bucket_name}/"))
        return await asyncio.to_thread(f.read_text, encoding="utf-8")

    async def exists(self, path: str) -> bool:
        return await asyncio.to_thread(self._file(path).exists)

    async def delete_prefix(self, prefix: str) -> int:
        import shutil

        target = self._file(prefix.rstrip("/"))

        def _delete() -> int:
            if not target.exists():
                return 0
            n = sum(1 for p in target.rglob("*") if p.is_file()) if target.is_dir() else 1
            shutil.rmtree(target) if target.is_dir() else target.unlink()
            return n

        return await asyncio.to_thread(_delete)


class MemoryBlobStore:
    """In-process store for tests and offline development."""

    def __init__(self, bucket: str = "memory"):
        self.bucket_name = bucket
        self.objects: dict[str, str] = {}

    async def put_text(self, path: str, text: str, content_type: str = "text/markdown") -> BlobRef:
        self.objects[path] = text
        return {"uri": f"gs://{self.bucket_name}/{path}", "sha256": sha256(text), "size": len(text.encode())}

    async def get_text(self, uri: str) -> str:
        return self.objects[uri.removeprefix(f"gs://{self.bucket_name}/")]

    async def exists(self, path: str) -> bool:
        return path in self.objects

    async def delete_prefix(self, prefix: str) -> int:
        keys = [k for k in self.objects if k.startswith(prefix)]
        for k in keys:
            del self.objects[k]
        return len(keys)


class CachedBlobReader:
    """Small LRU in front of a BlobStore. Safe because objects are content-addressed (immutable)."""

    def __init__(self, store: BlobStore, max_items: int = 64):
        self.store = store
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._max = max_items

    async def get_text(self, uri: str) -> str:
        if uri in self._cache:
            self._cache.move_to_end(uri)
            return self._cache[uri]
        text = await self.store.get_text(uri)
        self._cache[uri] = text
        if len(self._cache) > self._max:
            self._cache.popitem(last=False)
        return text

    async def get_json(self, uri: str) -> Any:
        return json.loads(await self.get_text(uri))
