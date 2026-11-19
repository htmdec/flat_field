"""Geometry refinement helpers, adapted from the pyFAI flat-field tutorial.

``extract_cpt`` is the tutorial's variant of pyFAI's automatic control-point extraction:
it honours the mask and stops after ``max_rings`` rings.
"""

from __future__ import annotations

import copy
import logging
import os

import numpy

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # cli_calibration imports silx.gui.qt

import pyFAI  # noqa: E402
from pyFAI.gui.cli_calibration import AbstractCalibration  # noqa: E402
from silx.image import marchingsquares  # noqa: E402

logger = pyFAI.gui.cli_calibration.logger
# headless peak picking logs one "No diffraction image available" error per ring; harmless
logging.getLogger("pyFAI.gui.peak_picker").setLevel(logging.CRITICAL)


def extract_cpt(self, method="massif", pts_per_deg=1.0, max_rings=numpy.iinfo(int).max):
    """Automatic keypoint extraction (tutorial version).

    :param method: method for keypoint extraction
    :param pts_per_deg: number of control points per azimuthal degree
    :param max_rings: extract at most max_rings
    """
    logger.info("in extract_cpt with method %s", method)
    assert self.ai
    assert self.calibrant
    assert self.peakPicker
    self.peakPicker.reset()
    self.peakPicker.init(method, False)
    if self.geoRef:
        self.ai.set_config(self.geoRef.get_config())
    tth = numpy.array([i for i in self.calibrant.get_2th() if i is not None])
    tth = numpy.unique(tth)
    tth_min = numpy.zeros_like(tth)
    tth_max = numpy.zeros_like(tth)
    delta = (tth[1:] - tth[:-1]) / 4.0
    tth_max[:-1] = delta
    tth_max[-1] = delta[-1]
    tth_min[1:] = -delta
    tth_min[0] = -delta[0]
    tth_max += tth
    tth_min += tth

    shape = self.peakPicker.data.shape
    if self.geoRef:
        ttha = self.geoRef.center_array(shape, unit="2th_rad", scale=False)
        chia = self.geoRef.center_array(shape, unit="chi_rad", scale=False)
    else:
        ttha = self.ai.center_array(shape, unit="2th_rad", scale=False)
        chia = self.ai.center_array(shape, unit="chi_rad", scale=False)
    rings = 0
    self.peakPicker.sync_init()
    if self.max_rings is None:
        self.max_rings = tth.size

    ms = marchingsquares.MarchingSquaresMergeImpl(ttha, self.mask, use_minmax_cache=True)
    for i in range(tth.size):
        if rings >= min(self.max_rings, max_rings):
            break
        mask1 = numpy.logical_and(ttha >= tth_min[i], ttha < tth_max[i])
        if self.mask is not None:
            numpy.logical_and(mask1, numpy.logical_not(self.mask), out=mask1)

        size = mask1.sum(dtype=int)
        if size > 0:
            rings += 1
            self.peakPicker.massif_contour(mask1)
            sub_data = self.peakPicker.data.ravel()[numpy.where(mask1.ravel())]
            mean = sub_data.mean(dtype=numpy.float64)
            std = sub_data.std(dtype=numpy.float64)
            upper_limit = mean + std
            mask2 = numpy.logical_and(self.peakPicker.data > upper_limit, mask1)
            size2 = mask2.sum(dtype=int)
            if size2 < 1000:
                upper_limit = mean
                numpy.logical_and(self.peakPicker.data > upper_limit, mask1, out=mask2)
                size2 = mask2.sum()
            # length of the arc:
            points = ms.find_pixels(tth[i])
            seeds = {(i[0], i[1]) for i in points if mask2[i[0], i[1]]}
            # max number of points: 360 points for a full circle
            azimuthal = chia[
                points[:, 0].clip(0, self.peakPicker.data.shape[0]),
                points[:, 1].clip(0, self.peakPicker.data.shape[1]),
            ]
            nb_deg_azim = numpy.unique(numpy.rad2deg(azimuthal).round()).size
            keep = int(nb_deg_azim * pts_per_deg)
            if keep == 0:
                continue
            dist_min = len(seeds) / 2.0 / keep
            logger.info(
                "Extracting datapoint for ring %s (2theta = %.2f deg); "
                "searching for %i pts out of %i with I>%.1f, dmin=%.1f"
                % (i, numpy.degrees(tth[i]), keep, size2, upper_limit, dist_min)
            )
            self.peakPicker.peaks_from_area(
                mask=mask2,
                Imin=upper_limit,
                keep=keep,
                method=method,
                ring=i,
                dmin=dist_min,
                seed=seeds,
            )

    if self.basename:
        self.peakPicker.points.save(self.basename + ".npt")
    if self.weighted:
        self.data = self.peakPicker.points.getWeightedList(self.peakPicker.data)
    else:
        self.data = self.peakPicker.points.getList()
    if self.geoRef:
        self.geoRef.data = numpy.array(self.data, dtype=numpy.float64)


def install_extract_cpt() -> None:
    """Monkey-patch the tutorial's ``extract_cpt`` onto pyFAI's calibration classes."""
    AbstractCalibration.extract_cpt = extract_cpt
    try:
        from pyFAI.gui.jupyter.calib import Calibration

        Calibration.extract_cpt = extract_cpt
    except Exception:  # pragma: no cover - widget stack not available
        pass


def predict_geometry(center_ai, center_coordinates, coordinates, scale=0.001, axes=(2, 1)):
    """Predict a position's geometry from the centre one by shifting the PONI.

    Tutorial convention (ESRF ID31): ``poni1 += dz*0.001`` and ``poni2 += dy*0.001`` with
    coordinates ``(x, y, z)`` in mm. ``axes`` gives the coordinate indices feeding
    (poni1, poni2).
    """
    delta = numpy.array(coordinates, dtype=float) - numpy.array(center_coordinates, dtype=float)
    ain = copy.copy(center_ai)
    ain.poni1 += delta[axes[0]] * scale
    ain.poni2 += delta[axes[1]] * scale
    return ain


def refine_position(
    calibration_data,
    mask,
    detector,
    calibrant,
    wavelength,
    initial_ai,
    max_rings=4,
    fixed=("rot1", "rot2"),
):
    """Extract control points on the calibrant rings and refine (tutorial loop body).

    Returns ``(ai, control_points)``.
    """
    install_extract_cpt()
    calibn = AbstractCalibration(
        calibration_data, mask, detector, wavelength=wavelength, calibrant=calibrant
    )
    calibn.preprocess()
    calibn.data = []
    calibn.geoRef = calibn.initgeoRef()
    calibn.geoRef.set_config(initial_ai.get_config())
    calibn.extract_cpt(max_rings=max_rings)
    calibn.fixed += list(fixed)
    calibn.geoRef.refine3(fix=calibn.fixed)
    return pyFAI.load(calibn.geoRef), calibn.peakPicker.points
