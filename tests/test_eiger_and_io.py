import json

import fabio
import h5py
import hdf5plugin  # noqa: F401
import numpy

from flat_field import load_eiger_master, maxima_position, save_flatfield
from flat_field.io import build_metadata, make_version


def _fake_eiger(tmp_path, stem="scan_point_0"):
    img = numpy.full((1, 6, 5), 100, numpy.uint32)
    img[0, 0, 0] = 0xFFFFFFFF  # flagged by the detector
    pm = numpy.zeros((6, 5), numpy.uint32)
    pm[0, 0] = 1
    pm[2, 3] = 8  # in mask but (pretend) not flagged in data
    with h5py.File(tmp_path / f"{stem}_data_000001.h5", "w") as f:
        f["entry/data/data"] = img
    with h5py.File(tmp_path / f"{stem}_master.h5", "w") as f:
        f["entry/data/data_000001"] = h5py.ExternalLink(
            f"{stem}_data_000001.h5", "/entry/data/data"
        )
        d = "entry/instrument/detector/"
        f[d + "detectorSpecific/pixel_mask"] = pm
        f[d + "detectorSpecific/photon_energy"] = 24209.7
        f[d + "detector_number"] = b"E-02-0375"
        f[d + "threshold_energy"] = 12104.8
        f[d + "flatfield_correction_applied"] = numpy.int8(1)
    return tmp_path / f"{stem}_master.h5"


def test_load_eiger_master(tmp_path):
    m = _fake_eiger(tmp_path)
    image, mask, meta = load_eiger_master(m)
    assert mask[0, 0] and mask[2, 3] and mask.sum() == 2
    assert numpy.isnan(image[0, 0]) and numpy.isnan(image[2, 3]) and image[1, 1] == 100
    assert meta["detector_number"] == "E-02-0375"
    assert abs(meta["photon_energy_eV"] - 24209.7) < 1e-6
    p = maxima_position(1, m, calibration_master=m)
    assert p.pixel_mask.sum() == 2 and p.calibration_data is not None


def test_save_flatfield(tmp_path):
    flat = numpy.ones((6, 5), numpy.float32)
    flat[0, 0] = numpy.nan
    meta = build_metadata(
        version=make_version(), detector={"id": "X"}, parameters={}, inputs=[], stats={}
    )
    ones, zeros = numpy.ones((6, 5)), numpy.zeros((6, 5))
    out = save_flatfield(tmp_path, flat, 1 / flat, ones, zeros, meta, "ff")
    assert numpy.isnan(fabio.open(str(out["edf"])).data[0, 0])
    rec = json.loads(out["json"].read_text())
    assert set(rec["files"]) == {"ff.edf", "ff.h5"} and len(rec["files"]["ff.edf"]["sha256"]) == 64
    with h5py.File(out["h5"]) as f:
        assert json.loads(f["flatfield"].attrs["metadata_json"])["version"] == meta["version"]
