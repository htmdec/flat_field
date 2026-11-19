"""Versioned storage of flat-fields on the data.htmdec.org Girder portal.

Layout (one Girder folder, set with ``FLATFIELD_FOLDER_ID``)::

    <flat-field folder>/                       folder meta: current_flatfield = {<detector>: {...}}
        flatfield_<detector>_<energy>keV_<version>   (one immutable item per calibration)
            <basename>.edf   pyFAI-ready flat
            <basename>.h5    flat + gain + n_valid + mask + metadata
            <basename>.json  metadata record
          item meta: data_type="xrd_flatfield", version, detector, energy, method, stats, prov, ...

Versions are never overwritten: publishing refuses an existing item name. "Promoting" a
version only updates the folder's ``current_flatfield`` pointer for that detector, so
workflows can ask for "current" while every older version stays retrievable.
Authentication follows the MAXIMA Dagster pipeline: the API key is sent in the request
body, never in a URL, so it cannot leak into logs or exception messages.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import requests
from girder_client import GirderClient

DEFAULT_API_URL = "https://data.htmdec.org/api/v1"
DATA_TYPE = "xrd_flatfield"
POINTER_KEY = "current_flatfield"


class PortalError(RuntimeError):
    """Raised for portal problems; never contains the API key."""


class _KeyInBodyClient(GirderClient):
    def authenticate(self, username=None, password=None, interactive=False, apiKey=None):
        if not apiKey:
            return super().authenticate(username, password, interactive=interactive)
        resp = self.post("api_key/token", data={"key": apiKey})
        self.setToken(resp["authToken"]["token"])


@dataclass
class PortalConfig:
    api_url: str = DEFAULT_API_URL
    api_key: str | None = None
    folder_id: str | None = None

    @classmethod
    def from_env(cls, dotenv: bool = True) -> "PortalConfig":
        """Read ``GIRDER_API_URL``, ``GIRDER_API_KEY`` and ``FLATFIELD_FOLDER_ID``
        (optionally from a ``.env`` file)."""
        if dotenv:
            try:
                from dotenv import load_dotenv

                load_dotenv()
            except ImportError:  # pragma: no cover
                pass
        return cls(
            api_url=os.getenv("GIRDER_API_URL", DEFAULT_API_URL),
            api_key=os.getenv("GIRDER_API_KEY") or None,
            folder_id=os.getenv("FLATFIELD_FOLDER_ID") or None,
        )


def connect(config: PortalConfig) -> GirderClient:
    client = _KeyInBodyClient(apiUrl=config.api_url)
    if config.api_key:
        try:
            client.authenticate(apiKey=config.api_key)
        except requests.RequestException as exc:
            msg = str(exc)
            for secret in {config.api_key, quote(config.api_key, safe="")}:
                msg = msg.replace(secret, "***")
            raise PortalError(
                f"Girder authentication failed ({type(exc).__name__}): {msg}"
            ) from None
    return client


def item_link(api_url: str, item_id: str) -> str:
    base = api_url.rstrip("/")
    if base.endswith("/api/v1"):
        base = base[: -len("/api/v1")]
    return f"{base}/#item/{item_id}"


def _safe(s: Any) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(s)).strip("-") or "unknown"


def item_name(detector_id: str, energy_keV: float | None, version: str) -> str:
    e = f"{energy_keV:.2f}keV" if energy_keV else "unknownE"
    return f"flatfield_{_safe(detector_id)}_{e}_{_safe(version)}"


def publish_flatfield(
    client: GirderClient,
    folder_id: str,
    files: Iterable[Path],
    metadata: dict[str, Any],
    detector_id: str,
    energy_keV: float | None,
    version: str,
    promote: bool = False,
    api_url: str = DEFAULT_API_URL,
) -> dict[str, Any]:
    """Create a new immutable item holding ``files`` and attach ``metadata``.

    If ``promote`` is True, also point the folder's ``current_flatfield[detector_id]`` at it.
    Returns ``{"item_id", "name", "link", "promoted"}``.
    """
    name = item_name(detector_id, energy_keV, version)
    if any(True for _ in client.listItem(folder_id, name=name)):
        raise PortalError(f"Item {name!r} already exists; versions are immutable.")

    item = client.createItem(
        folder_id, name, description="Flat-field calibration (pyFAI, amorphous scattering)"
    )
    try:
        for path in files:
            path = Path(path)
            client.uploadFileToItem(item["_id"], str(path))
        meta = dict(metadata)
        meta.update(
            {
                "data_type": DATA_TYPE,
                "version": version,
                "detector_id": detector_id,
                "energy_keV": energy_keV,
            }
        )
        client.addMetadataToItem(item["_id"], _jsonable(meta))
    except Exception:
        # leave nothing half-published
        try:
            client.delete(f"item/{item['_id']}")
        except Exception:
            pass
        raise

    result = {
        "item_id": item["_id"],
        "name": name,
        "link": item_link(api_url, item["_id"]),
        "promoted": False,
    }
    if promote:
        promote_version(client, folder_id, item["_id"], detector_id, version, energy_keV, api_url)
        result["promoted"] = True
    return result


def promote_version(
    client: GirderClient,
    folder_id: str,
    item_id: str,
    detector_id: str,
    version: str,
    energy_keV: float | None = None,
    api_url: str = DEFAULT_API_URL,
) -> dict[str, Any]:
    """Make ``item_id`` the current flat-field for ``detector_id`` (keeps other detectors)."""
    folder = client.getFolder(folder_id)
    pointers = dict((folder.get("meta") or {}).get(POINTER_KEY) or {})
    pointers[_safe(detector_id)] = {
        "item_id": item_id,
        "version": version,
        "energy_keV": energy_keV,
        "link": item_link(api_url, item_id),
    }
    client.addMetadataToFolder(folder_id, {POINTER_KEY: pointers})
    return pointers


def list_flatfields(client: GirderClient, folder_id: str, detector_id: str | None = None):
    """All published versions in the folder, newest first."""
    items = [
        it
        for it in client.listItem(folder_id)
        if (it.get("meta") or {}).get("data_type") == DATA_TYPE
        and (detector_id is None or it["meta"].get("detector_id") == detector_id)
    ]
    return sorted(items, key=lambda it: it["meta"].get("version", ""), reverse=True)


def resolve_flatfield(
    client: GirderClient, folder_id: str, detector_id: str, version: str = "current"
) -> dict[str, Any]:
    """Return the item for ``version`` ("current", "latest", a version label or an item id)."""
    if version == "current":
        meta = client.getFolder(folder_id).get("meta") or {}
        ptr = (meta.get(POINTER_KEY) or {}).get(_safe(detector_id))
        if not ptr:
            raise PortalError(f"No current flat-field set for detector {detector_id!r}.")
        return client.getItem(ptr["item_id"])
    items = list_flatfields(client, folder_id, detector_id)
    if version == "latest":
        if not items:
            raise PortalError(f"No flat-fields published for detector {detector_id!r}.")
        return items[0]
    for it in items:
        if it["_id"] == version or it["meta"].get("version") == version:
            return it
    raise PortalError(f"Flat-field version {version!r} not found for detector {detector_id!r}.")


def fetch_flatfield(
    client: GirderClient,
    folder_id: str,
    detector_id: str,
    dest,
    version: str = "current",
) -> dict[str, Any]:
    """Download a flat-field version into ``dest``; returns item metadata and local paths."""
    item = resolve_flatfield(client, folder_id, detector_id, version)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    paths = {}
    for f in client.listFile(item["_id"]):
        p = dest / f["name"]
        client.downloadFile(f["_id"], str(p))
        paths[f["name"]] = p
    return {"item": item, "paths": paths}


def _jsonable(obj):
    """Girder metadata must be JSON and keys may not contain '.' or start with '$'."""
    import numpy

    if isinstance(obj, dict):
        return {str(k).replace(".", "_").lstrip("$"): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, numpy.generic):
        return obj.item()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, float) and not numpy.isfinite(obj):
        return None
    return obj
