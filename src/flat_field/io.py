"""Writing the flat-field and its provenance record to disk."""

from __future__ import annotations

import getpass
import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fabio
import h5py
import numpy

DATA_TYPE = "xrd_flatfield"
CONVENTION = (
    "pyFAI divide convention: corrected = raw / flat. flat = 1/gain, where "
    "gain = ideal (median azimuthal profile back-projected) / measured. NaN = undetermined."
)


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit() -> str | None:
    try:
        here = Path(__file__).resolve().parent
        out = subprocess.run(
            ["git", "-C", str(here), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        commit = out.stdout.strip()
        if not commit:
            return None
        dirty = subprocess.run(
            ["git", "-C", str(here), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        return commit + ("-dirty" if dirty else "")
    except Exception:
        return None


def make_version(now: datetime | None = None) -> str:
    """Immutable version label, UTC timestamp, e.g. ``2026-11-19T203012Z``."""
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H%M%SZ")


def provenance() -> dict[str, Any]:
    import pyFAI

    from . import __version__

    return {
        "package": "flat-field",
        "package_version": __version__,
        "git_commit": _git_commit(),
        "pyFAI_version": pyFAI.version,
        "python": platform.python_version(),
        "host": platform.node(),
        "user": getpass.getuser(),
        "time": datetime.now(timezone.utc).isoformat(),
    }


def build_metadata(
    *,
    version: str,
    detector: dict[str, Any],
    parameters: dict[str, Any],
    inputs: list[dict[str, Any]],
    stats: dict[str, Any],
    notes: str = "",
) -> dict[str, Any]:
    """Assemble the provenance/metadata record stored with each flat-field version."""
    return {
        "data_type": DATA_TYPE,
        "version": version,
        "convention": CONVENTION,
        "method": {
            "name": "flat-field from amorphous scattering",
            "reference": "Weng et al., J. Synchrotron Rad. 30, 546-554 (2023), "
            "doi:10.1107/S1600577523001157; pyFAI tutorial 'Flat-field calibration "
            "from amorphous scattering'",
        },
        "detector": detector,
        "parameters": parameters,
        "inputs": inputs,
        "stats": stats,
        "notes": notes,
        "prov": provenance(),
    }


def save_flatfield(
    out_dir,
    flat,
    gain,
    n_valid,
    mask,
    metadata: dict[str, Any],
    basename: str,
) -> dict[str, Any]:
    """Write the calibration bundle.

    * ``<basename>.edf``   pyFAI-ready flat (float32, divide convention), as in the tutorial
    * ``<basename>.h5``    flat, gain, n_valid, mask and the metadata JSON in one file
    * ``<basename>.json``  metadata record (also attached to the portal item), incl. checksums
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    edf = out_dir / f"{basename}.edf"
    h5 = out_dir / f"{basename}.h5"
    js = out_dir / f"{basename}.json"

    flat32 = numpy.asarray(flat, dtype=numpy.float32)
    header = {
        "data_type": DATA_TYPE,
        "version": str(metadata.get("version", "")),
        "convention": "divide",
    }
    fabio.edfimage.EdfImage(data=flat32, header=header).write(str(edf))

    with h5py.File(h5, "w") as f:
        g = f.create_group("flatfield")
        g.attrs["NX_class"] = "NXcollection"
        g.attrs["convention"] = CONVENTION
        g.create_dataset("flat", data=flat32, compression="gzip")
        g.create_dataset("gain", data=numpy.asarray(gain, numpy.float32), compression="gzip")
        g.create_dataset("n_valid", data=numpy.asarray(n_valid, numpy.uint8), compression="gzip")
        g.create_dataset("mask", data=numpy.asarray(mask, numpy.int8), compression="gzip")
        g.attrs["metadata_json"] = json.dumps(metadata, default=str)

    record = dict(metadata)
    record["files"] = {
        edf.name: {"sha256": sha256(edf), "size": edf.stat().st_size, "role": "pyfai_flat"},
        h5.name: {"sha256": sha256(h5), "size": h5.stat().st_size, "role": "bundle"},
    }
    js.write_text(json.dumps(record, indent=2, default=str))
    return {"edf": edf, "h5": h5, "json": js, "record": record}
