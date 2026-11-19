import numpy
import pyFAI
from pyFAI.detectors import Detector
from pyFAI.integrator.azimuthal import AzimuthalIntegrator

from flat_field import build_mask, flat_stats, merge_flats, position_flat, to_pyfai_flat

SHAPE = (160, 180)


def _ai(poni1, poni2):
    det = Detector(pixel1=1e-4, pixel2=1e-4, max_shape=SHAPE)
    return AzimuthalIntegrator(dist=0.1, poni1=poni1, poni2=poni2, detector=det, wavelength=1e-10)


def _ideal(ai):
    q = numpy.linspace(0.1, 60, 400)
    profile = 1000 * numpy.exp(-q / 40) + 200  # smooth amorphous-like profile
    return ai.calcfrom1d(q, profile, SHAPE, dim1_unit=pyFAI.units.Q_NM)


def test_recovers_known_gain_from_several_positions():
    rng = numpy.random.default_rng(0)
    true_gain = rng.normal(1.0, 0.08, SHAPE)  # gain = ideal / measured
    flats = []
    for p1, p2 in [(0.008, 0.009), (0.004, 0.009), (0.012, 0.009), (0.008, 0.004), (0.008, 0.014)]:
        ai = _ai(p1, p2)
        measured = _ideal(ai) / true_gain
        mask = build_mask(ai.detector, [measured])
        ai.detector.mask = mask
        flat, _ = position_flat(ai, measured, mask, npt=256)
        flats.append(flat)
    gain, n_valid = merge_flats(flats, min_valid=3)
    ok = numpy.isfinite(gain)
    assert ok.mean() > 0.8
    err = numpy.abs(gain[ok] - true_gain[ok])
    assert numpy.median(err) < 0.01
    assert numpy.corrcoef(gain[ok], true_gain[ok])[0, 1] > 0.98
    assert n_valid.max() == 5


def test_min_valid_and_mask():
    a = numpy.ones((4, 4))
    b = numpy.ones((4, 4))
    b[0, 0] = numpy.nan
    gain, n = merge_flats([a, b], min_valid=2)
    assert numpy.isnan(gain[0, 0]) and n[0, 0] == 1 and gain[1, 1] == 1


def test_pyfai_flat_flattens_integration():
    rng = numpy.random.default_rng(1)
    true_gain = rng.normal(1.0, 0.1, SHAPE)
    ai = _ai(0.008, 0.009)
    measured = _ideal(ai) / true_gain
    flat = to_pyfai_flat(true_gain)
    corrected = measured / flat
    numpy.testing.assert_allclose(corrected, _ideal(ai), rtol=1e-5)
    s = flat_stats(flat)
    assert s["valid_pixels"] == flat.size and 0.8 < s["median"] < 1.2
