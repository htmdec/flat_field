"""Flat-field maths: per-position response maps and their merge."""

from __future__ import annotations

import numpy
import pyFAI


def build_mask(detector, images, extra_masks=()):
    """Tutorial mask: static detector mask, plus any pixel that is negative in any image,
    plus any extra boolean masks (e.g. DECTRIS ``pixel_mask``), plus non-finite pixels.

    Returns an int8 array suitable for ``detector.mask``.
    """
    mask = detector.mask.astype(bool) if detector.mask is not None else numpy.zeros(
        detector.shape, bool
    )
    for img in images:
        if img is None:
            continue
        img = numpy.asarray(img)
        with numpy.errstate(invalid="ignore"):
            mask |= ~numpy.isfinite(img) | (img < 0)
    for m in extra_masks:
        if m is not None:
            mask |= numpy.asarray(m, bool)
    return mask.astype(numpy.int8)


def position_flat(
    ai, scattering_data, mask, npt=512, polarization=None, method=("full", "csr", "cython")
):
    """Gain map for one position: ideal (median azimuthal profile back-projected) / measured.

    Masked, non-finite and non-positive pixels are NaN. Also returns the median profile.
    """
    data = numpy.asarray(scattering_data, dtype=numpy.float64)
    md = ai.medfilt1d_ng(
        data, npt, polarization_factor=polarization, method=method, mask=mask
    )
    rebuilt = ai.calcfrom1d(
        md.radial,
        md.intensity,
        data.shape,
        dim1_unit=pyFAI.units.Q_NM,
        polarization_factor=polarization,
    )
    with numpy.errstate(divide="ignore", invalid="ignore"):
        flat = rebuilt / data
    bad = numpy.asarray(mask, bool) | ~numpy.isfinite(data) | (data <= 0) | ~numpy.isfinite(flat)
    flat[bad] = numpy.nan
    return flat, md


def merge_flats(flats, min_valid=5):
    """Pixel-wise median over positions; pixels measured at fewer than ``min_valid``
    positions are NaN. Returns ``(gain, n_valid)``."""
    stack = numpy.asarray(flats, dtype=numpy.float64)
    n_valid = numpy.isfinite(stack).sum(axis=0)
    with numpy.errstate(all="ignore"):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            gain = numpy.nanmedian(stack, axis=0)
    gain[n_valid < min_valid] = numpy.nan
    return gain, n_valid.astype(numpy.uint8)


def robust_spread(values):
    """Half of the 16-84 percentile range of the finite values (~1 sigma, insensitive to
    hot pixels)."""
    v = numpy.asarray(values, dtype=numpy.float64)
    v = v[numpy.isfinite(v)]
    if v.size == 0:
        return float("nan")
    p16, p84 = numpy.percentile(v, [16, 84])
    return float(0.5 * (p84 - p16))


def pixel_scale_spread(values, size=7):
    """Spread of the pixel-to-pixel part only: the map divided by its local median
    (``size`` x ``size``), so smooth, position-dependent structure is ignored."""
    from scipy.ndimage import median_filter

    v = numpy.asarray(values, dtype=numpy.float64)
    ok = numpy.isfinite(v)
    if not ok.any():
        return float("nan")
    filled = numpy.where(ok, v, numpy.median(v[ok]))
    with numpy.errstate(divide="ignore", invalid="ignore"):
        hp = v / median_filter(filled, size=size, mode="nearest")
    return robust_spread(hp)


def to_pyfai_flat(gain):
    """pyFAI *divides* by the flat-field, so store the reciprocal of the gain (float32).
    Undetermined pixels stay NaN."""
    with numpy.errstate(divide="ignore", invalid="ignore"):
        return (1.0 / numpy.asarray(gain, dtype=numpy.float64)).astype(numpy.float32)


def flat_stats(flat):
    """Summary numbers for the metadata record (computed on the pyFAI-convention flat)."""
    f = numpy.asarray(flat, dtype=numpy.float64)
    ok = numpy.isfinite(f)
    v = f[ok]
    if v.size == 0:
        return {"valid_pixels": 0, "total_pixels": int(f.size)}
    p = numpy.percentile(v, [0.1, 1, 50, 99, 99.9])
    return {
        "valid_pixels": int(ok.sum()),
        "total_pixels": int(f.size),
        "valid_fraction": float(ok.mean()),
        "mean": float(v.mean()),
        "std": float(v.std()),
        "min": float(v.min()),
        "max": float(v.max()),
        "p0_1": float(p[0]),
        "p1": float(p[1]),
        "median": float(p[2]),
        "p99": float(p[3]),
        "p99_9": float(p[4]),
        "robust_spread": robust_spread(v),
    }
