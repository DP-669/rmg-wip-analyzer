"""
Getting audio onto local disk.

Four routes, one destination. Everything ends as a file path plus a label.

  1. Uploaded files    — the file picker and drag-and-drop both land here.
  2. Pasted links      — one Dropbox link per line.
  3. Folder crawl      — a Dropbox folder link, listed via the API.
  4. Local paths       — for command-line use and testing.
"""

import os
import re
import shutil
import tempfile

import requests

from .audio import ACCEPTED_EXTENSIONS

HTML_MARKERS = ("text/html", "text/plain", "application/xhtml")

# Dropbox returns HTML for folder links, expired links and password walls.
# Catching that here produces a useful message instead of a corrupt-file error.


class SourceError(Exception):
    """The audio could not be retrieved."""


# ------------------------------------------------------------------ links

def to_direct_link(url: str) -> str:
    """Rewrite a Dropbox share link so it returns raw bytes."""
    url = url.strip()
    if not url:
        raise SourceError("Empty link.")

    if "dropbox.com" not in url:
        return url  # some other host; try it as-is

    url = re.sub(r"[?&]st=[^&]*", "", url)

    if "dl=0" in url:
        return url.replace("dl=0", "dl=1")
    if "dl=1" in url or "raw=1" in url:
        return url

    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}dl=1"


def looks_like_folder(url: str) -> bool:
    """Dropbox folder links use /scl/fo/ or /sh/."""
    return "/scl/fo/" in url or "/sh/" in url


def filename_from(url: str, fallback: str = "track") -> str:
    """Best-effort filename from a URL."""
    path = url.split("?")[0].rstrip("/")
    name = os.path.basename(path)
    if name and os.path.splitext(name)[1].lower() in ACCEPTED_EXTENSIONS:
        return name
    return f"{fallback}.mp3"


def download(url: str, into_dir: str, timeout: int = 180) -> str:
    """
    Fetch a link to local disk. Raises SourceError with a message a
    non-technical person can act on.
    """
    direct = to_direct_link(url)

    if looks_like_folder(url):
        raise SourceError(
            "This is a folder link, not a file link. Use the folder tab to "
            "list its contents, or open the folder in Dropbox and copy the "
            "link to one track."
        )

    try:
        response = requests.get(direct, stream=True, timeout=timeout)
        response.raise_for_status()
    except requests.exceptions.Timeout as exc:
        raise SourceError("Dropbox did not respond in time. Try again.") from exc
    except requests.exceptions.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        if code == 404:
            raise SourceError(
                "Dropbox returned 'not found'. The link has expired, or the "
                "file has been moved or renamed."
            ) from exc
        raise SourceError(f"Dropbox refused the request (HTTP {code}).") from exc
    except requests.RequestException as exc:
        raise SourceError(f"Could not reach the link. {exc}") from exc

    content_type = response.headers.get("Content-Type", "").lower()
    if any(marker in content_type for marker in HTML_MARKERS):
        raise SourceError(
            "This link returned a web page instead of audio. It is usually "
            "password-protected, expired, or a folder rather than a file."
        )

    name = filename_from(url)
    dest = os.path.join(into_dir, name)

    with open(dest, "wb") as handle:
        for chunk in response.iter_content(chunk_size=65536):
            handle.write(chunk)

    return dest


# --------------------------------------------------------- folder listing

def list_dropbox_folder(shared_link: str, access_token: str) -> list:
    """
    List audio files inside a shared Dropbox folder, at any depth.

    Uses the Dropbox API rather than scraping the share page, which is why an
    access token is needed. Returns dicts with name, path, size and a
    downloadable link.
    """
    if not access_token:
        raise SourceError(
            "No Dropbox access token is configured, so folders cannot be "
            "listed. Paste individual file links instead, or add "
            "DROPBOX_ACCESS_TOKEN to the app's secrets."
        )

    endpoint = "https://api.dropboxapi.com/2/files/list_folder"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    body = {
        "path": "",
        "shared_link": {"url": shared_link.strip()},
        "recursive": True,
        "limit": 2000,
    }

    entries = []
    while True:
        response = requests.post(endpoint, headers=headers, json=body, timeout=60)
        if response.status_code == 401:
            raise SourceError(
                "Dropbox rejected the access token. It has probably expired "
                "and needs regenerating."
            )
        if not response.ok:
            raise SourceError(
                f"Dropbox could not list this folder (HTTP {response.status_code}). "
                "Check that the link is a folder you have access to."
            )

        payload = response.json()
        entries.extend(payload.get("entries", []))

        if not payload.get("has_more"):
            break

        endpoint = "https://api.dropboxapi.com/2/files/list_folder/continue"
        body = {"cursor": payload["cursor"]}

    files = []
    for entry in entries:
        if entry.get(".tag") != "file":
            continue
        name = entry.get("name", "")
        if os.path.splitext(name)[1].lower() not in ACCEPTED_EXTENSIONS:
            continue
        rel = entry.get("path_display") or entry.get("path_lower") or name
        files.append({
            "name": name,
            "path": rel,
            "folder": os.path.dirname(rel),
            "size_mb": round(entry.get("size", 0) / (1024 * 1024), 2),
            "shared_link": shared_link.strip(),
            "rel_path": rel,
        })

    if not files:
        raise SourceError(
            "No audio files were found in that folder. Check the link points "
            "to the composer's folder and not to a parent directory."
        )

    files.sort(key=lambda f: (f["folder"], f["name"]))
    return files


def download_from_shared_folder(
    shared_link: str, rel_path: str, access_token: str, into_dir: str
) -> str:
    """Download one file from inside a shared folder, via the API."""
    if not access_token:
        raise SourceError("No Dropbox access token is configured.")

    import json as _json

    args = _json.dumps({
        "url": shared_link.strip(),
        "path": rel_path if rel_path.startswith("/") else f"/{rel_path}",
    })

    response = requests.post(
        "https://content.dropboxapi.com/2/sharing/get_shared_link_file",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Dropbox-API-Arg": args,
        },
        stream=True,
        timeout=180,
    )

    if not response.ok:
        raise SourceError(
            f"Dropbox would not return this file (HTTP {response.status_code}). "
            "It may have been moved since the folder was listed."
        )

    dest = os.path.join(into_dir, os.path.basename(rel_path))
    with open(dest, "wb") as handle:
        for chunk in response.iter_content(chunk_size=65536):
            handle.write(chunk)
    return dest


# --------------------------------------------------------------- uploads

def save_upload(uploaded_file, into_dir: str) -> str:
    """Persist a Streamlit upload to disk."""
    dest = os.path.join(into_dir, uploaded_file.name)
    with open(dest, "wb") as handle:
        handle.write(uploaded_file.getbuffer())
    return dest


def workspace() -> str:
    """A temp directory for one run."""
    return tempfile.mkdtemp(prefix="rmg_wip_")


def cleanup(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)
