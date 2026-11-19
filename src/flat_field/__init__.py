"""Flat-field calibration from amorphous scattering, after the pyFAI tutorial
"Flat-field calibration from amorphous scattering" (Weng et al., J. Synchrotron Rad. 30, 546, 2023),
with helpers for MAXIMA (DECTRIS EIGER2) data and versioned publishing to data.htmdec.org.
"""

import hdf5plugin  # noqa: F401  (registers the bitshuffle/LZ4 filters used by DECTRIS and ESRF files)

from .flatfield import (
    build_mask,
    flat_stats,
    merge_flats,
    pixel_scale_spread,
    position_flat,
    robust_spread,
    to_pyfai_flat,
)
from .io import save_flatfield
from .positions import Position, load_eiger_master, load_esrf_position, maxima_position

__version__ = "0.1.0"

__all__ = [
    "Position",
    "load_eiger_master",
    "load_esrf_position",
    "maxima_position",
    "build_mask",
    "merge_flats",
    "position_flat",
    "flat_stats",
    "robust_spread",
    "pixel_scale_spread",
    "to_pyfai_flat",
    "save_flatfield",
    "__version__",
]
