"""Loading calibration + amorphous-scattering images for each detector position."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import h5py
import hdf5plugin  # noqa: F401
import numpy

# DECTRIS writes masked pixels as 2**bit_depth - 1 when pixel_mask_applied is on.
EIGER_FLAG_32 = numpy.uint32(0xFFFFFFFF)

_DET = "entry/instrument/detector/"
_DS = _DET + "detectorSpecific/"


@dataclass
class Position:
    """All data related to one of the positions (as in the pyFAI tutorial)."""

    position: Any
    calibration_idx: Any = None
    scattering_idx: Any = None
    coordinates: tuple = ()
    calibration_data: Any = None
    scattering_data: Any = None
    poni: Any = None
    ai: Any = None
    control_points: Any = None
    flat: Any = None
    # extra, not in the tutorial: pixel mask + metadata read from the files
    pixel_mask: Any = None
    meta: dict = field(default_factory=dict)

    @classmethod
    def init(
        cls,
        h5_file,
        position,
        calibration_idx,
        scattering_idx,
        detector_name="p3",
        positioners=("cncx", "cncy", "cncz"),
    ):
        """Tutorial loader for the ESRF ID31 Bliss file (one HDF5 file, one entry per scan)."""
        return load_esrf_position(
            h5_file, position, calibration_idx, scattering_idx, detector_name, positioners
        )


def load_esrf_position(
    h5_file,
    position,
    calibration_idx,
    scattering_idx,
    detector_name="p3",
    positioners=("cncx", "cncy", "cncz"),
) -> Position:
    with h5py.File(h5_file, "r") as h:
        keys = list(h.keys())

        def entry(idx):
            ids = [i for i in keys if i.startswith(f"{idx}.")]
            if not ids:
                raise IndexError(f"no such Entry {idx}")
            return h[ids[0]]

        cal = entry(calibration_idx)
        calibration_data = cal[f"measurement/{detector_name}"][0]
        sca = entry(scattering_idx)
        scattering_data = sca[f"measurement/{detector_name}"][0]
        coordinates = tuple(
            float(sca[f"instrument/positioners/{p}"][()]) for p in positioners
        )
    return Position(
        position,
        calibration_idx,
        scattering_idx,
        coordinates,
        calibration_data,
        scattering_data,
        meta={"source": str(h5_file)},
    )


def _scalar(h, path, default=None):
    if path not in h:
        return default
    v = h[path][()]
    if isinstance(v, bytes):
        return v.decode()
    if hasattr(v, "item"):
        return v.item()
    return v


def load_eiger_master(master_path, frame: int = 0) -> tuple[numpy.ndarray, numpy.ndarray, dict]:
    """Read one frame, the detector pixel mask and key metadata from a DECTRIS *_master.h5.

    Returns ``(image, mask, meta)``. ``image`` is float64 with flagged pixels set to NaN;
    ``mask`` is True where ``pixel_mask != 0`` or the pixel holds the 2**32-1 flag value.
    The matching ``*_data_000001.h5`` must sit next to the master file.
    """
    master_path = Path(master_path)
    with h5py.File(master_path, "r") as h:
        raw = h["entry/data/data_000001"][frame]
        pixel_mask = h[_DS + "pixel_mask"][()] if _DS + "pixel_mask" in h else None
        meta = {
            "source": master_path.name,
            "description": _scalar(h, _DET + "description"),
            "detector_number": _scalar(h, _DET + "detector_number"),
            "sensor_material": _scalar(h, _DET + "sensor_material"),
            "sensor_thickness_m": _scalar(h, _DET + "sensor_thickness"),
            "photon_energy_eV": _scalar(h, _DS + "photon_energy"),
            "element": _scalar(h, _DS + "element"),
            "threshold_energy_eV": _scalar(h, _DET + "threshold_energy"),
            "wavelength_A": _scalar(h, "entry/instrument/beam/incident_wavelength"),
            "count_time_s": _scalar(h, _DET + "count_time"),
            "data_collection_date": _scalar(h, _DS + "data_collection_date"),
            "firmware": _scalar(h, _DS + "eiger_fw_version"),
            "flatfield_correction_applied": _scalar(h, _DET + "flatfield_correction_applied"),
            "countrate_correction_applied": _scalar(h, _DET + "countrate_correction_applied"),
            "pixel_mask_applied": _scalar(h, _DET + "pixel_mask_applied"),
            "virtual_pixel_correction_applied": _scalar(
                h, _DET + "virtual_pixel_correction_applied"
            ),
        }
    flagged = raw == numpy.iinfo(raw.dtype).max if raw.dtype.kind == "u" else numpy.zeros(
        raw.shape, bool
    )
    mask = flagged.copy()
    if pixel_mask is not None:
        mask |= pixel_mask != 0
    image = raw.astype(numpy.float64)
    image[mask] = numpy.nan
    return image, mask, meta


def maxima_position(
    position,
    scattering_master,
    calibration_master=None,
    coordinates=(0.0, 0.0, 0.0),
    poni=None,
) -> Position:
    """Build a Position from MAXIMA (EIGER2) files.

    ``poni`` may be a path to an existing PONI file for this position (e.g. the one the
    MAXIMA Dagster pipeline produced from the calibrant); otherwise the geometry is refined
    from ``calibration_master`` in the notebook.
    """
    scat, mask, meta = load_eiger_master(scattering_master)
    cal = None
    if calibration_master is not None:
        cal, cal_mask, _ = load_eiger_master(calibration_master)
        mask = mask | cal_mask
    return Position(
        position=position,
        calibration_idx=str(calibration_master) if calibration_master else None,
        scattering_idx=str(scattering_master),
        coordinates=tuple(coordinates),
        calibration_data=cal,
        scattering_data=scat,
        poni=str(poni) if poni else None,
        pixel_mask=mask,
        meta=meta,
    )
