"""Remote document import: any HTTPS URL, with Google Drive share links
normalized to direct-download form.

Scope note: this covers publicly shared Drive files (uc?export=download) —
the demo-honest subset. Private Drive access would need OAuth/service-account
credentials and lives behind the same `download_remote` seam when that day
comes.
"""
import re

import httpx

_DRIVE_PATTERNS = [
    re.compile(r"drive\.google\.com/file/d/([\w-]+)"),
    re.compile(r"drive\.google\.com/open\?.*?id=([\w-]+)"),
    re.compile(r"drive\.google\.com/uc\?.*?id=([\w-]+)"),
]

_CONTENT_DISPOSITION_FILENAME = re.compile(r'filename="?([^";]+)"?', re.I)


class RemoteDownloadError(Exception):
    pass


class RemoteFileTooLargeError(Exception):
    pass


def normalize_url(url: str) -> str:
    """Google Drive share link -> direct download URL; anything else untouched."""
    for pattern in _DRIVE_PATTERNS:
        match = pattern.search(url)
        if match:
            return f"https://drive.google.com/uc?export=download&id={match.group(1)}"
    return url


def filename_from_headers(headers: httpx.Headers) -> str | None:
    disposition = headers.get("content-disposition", "")
    match = _CONTENT_DISPOSITION_FILENAME.search(disposition)
    return match.group(1).strip() if match else None


async def download_remote(url: str, *, max_bytes: int) -> tuple[bytes, str | None]:
    """Returns (content, filename-from-headers-or-path). Size is enforced
    while streaming — a huge remote file aborts early instead of buffering."""
    target = normalize_url(url)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            async with client.stream("GET", target) as response:
                response.raise_for_status()
                buffer = bytearray()
                async for part in response.aiter_bytes():
                    buffer.extend(part)
                    if len(buffer) > max_bytes:
                        raise RemoteFileTooLargeError(f"Remote file exceeds {max_bytes} bytes")
                filename = filename_from_headers(response.headers)
                if not filename:
                    tail = httpx.URL(str(response.url)).path.rsplit("/", 1)[-1]
                    filename = tail or None
                return bytes(buffer), filename
    except RemoteFileTooLargeError:
        raise
    except httpx.HTTPError as exc:
        raise RemoteDownloadError(f"Download failed: {exc}") from exc
