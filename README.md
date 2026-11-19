# flat_field

Flat-field calibration of X-ray area detectors from **amorphous scattering**, packaged as a
Jupyter notebook. A finished calibration can be stored as a **versioned correction** on the
HTMDEC data portal (`data.htmdec.org`, Girder) so processing workflows can fetch it.

The notebook is a conversion of the pyFAI tutorial
[Flat-field calibration from amorphous scattering](https://www.silx.org/doc/pyFAI/dev/usage/tutorial/Flatfield.html),
which implements the method of Weng *et al.*, *J. Synchrotron Rad.* **30**, 546–554 (2023),
[doi:10.1107/S1600577523001157](https://doi.org/10.1107/S1600577523001157). The method doesn't
need even illumination: it uses the scattering from an amorphous sample, which depends only on
the scattering angle. That makes it usable with a beam much smaller than the detector, as on MAXIMA.

## Quick start

```bash
uv sync                                   # create .venv from uv.lock
uv run jupyter lab notebooks/flatfield_calibration.ipynb
```

Run all cells with `DATA_SOURCE = "tutorial"` to reproduce the pyFAI example. It downloads the
ESRF ID31 data (about 67 MB) on first use. By default the centre geometry is loaded from
`notebooks/tutorial_center.poni` (the tutorial's published centre geometry) and refined
automatically on the calibrant rings, so no clicking is needed. To pick the rings by hand as in
the original tutorial, set `INTERACTIVE_CALIBRATION = True`. Section 6 of the notebook explains
how; on a Mac, use a two-finger click or N + click, not Ctrl-click.

## MAXIMA (EIGER2 CdTe 1M)

Set `DATA_SOURCE = "maxima"` and list one entry per position in `MAXIMA["positions"]`:

```python
MAXIMA["positions"] = [
    dict(position=0, scattering=".../amorphous_p0_master.h5",
         poni=".../XRD_calibrant_data_000001.poni"),          # existing geometry, or
    dict(position=1, scattering=".../amorphous_p1_master.h5",
         calibration=".../XRD_calibrant_master.h5",            # refine from a calibrant,
         coordinates=(0, 0, 5)),                               # stage offset (mm) vs. centre
    ...
]
```

* Each `*_master.h5` needs its `*_data_000001.h5` next to it.
* The DECTRIS `pixel_mask` and the 2³²−1 flag value are masked automatically.
* Use `polarization=0.0` (unpolarized lab source) unless `guess_polarization` says otherwise.
* The EIGER2 already applies DECTRIS's factory flatfield, so the result is a **residual**
  correction applied on top of it. The detector settings it was measured with (energy,
  threshold, serial number, which corrections were on) are recorded in the metadata.
* The method needs the pattern to land on different pixels at different positions, so that the
  median removes position-dependent artefacts (beam-stop shadow, gaps, parasitic scatter). With
  fewer than `MIN_VALID` (default 5) valid positions, a pixel is left undetermined (NaN).

## Outputs

For each run, the notebook writes `output/flatfield_<detector>_<energy>keV_<version>.{edf,h5,json}`:

| File | Content |
|---|---|
| `.edf` | pyFAI-ready flat (float32, **divide** convention: `corrected = raw / flat`), as in the tutorial |
| `.h5` | `flatfield/flat`, `gain`, `n_valid`, `mask` plus the metadata JSON |
| `.json` | metadata record: detector, energy, threshold, inputs and geometries, parameters, statistics, QC, software versions, git commit, SHA-256 of the files |

The version label is the UTC time of the run, for example `2026-11-19T204113Z`.

## Publishing to data.htmdec.org

Copy `.env.example` to `.env` and fill in `GIRDER_API_KEY` and `FLATFIELD_FOLDER_ID` (the Girder
folder that holds flat-fields). Then set `PUBLISH = True` and, optionally, `PROMOTE = True` in the
notebook's parameter cell.

* Each calibration becomes a **new, immutable item**
  `flatfield_<detector>_<energy>keV_<version>` holding the three files. The metadata record is
  attached to the item with `data_type = "xrd_flatfield"`. Publishing refuses to overwrite an
  existing version.
* **Promoting** sets the folder metadata `current_flatfield[<detector>]` to that item. Workflows
  ask for "current", and older versions stay available by label or item id, so a reprocessing
  run can pin the exact flat-field it used.
* The API key is sent in the request body, as in the MAXIMA Dagster pipeline, so it never
  appears in URLs or logs.

Using a flat-field from a workflow:

```python
from flat_field import portal
import fabio

cfg = portal.PortalConfig.from_env()
gc = portal.connect(cfg)
got = portal.fetch_flatfield(gc, cfg.folder_id, "E-02-0375", "flatfields/", version="current")
edf = next(p for name, p in got["paths"].items() if name.endswith(".edf"))
flat = fabio.open(str(edf)).data
result = ai.integrate1d(img, 10000, unit="q_nm^-1", flat=flat, mask=pixel_mask != 0)
# record got["item"]["meta"]["version"] with the processed data
```

`portal.list_flatfields(...)` lists all versions. `portal.promote_version(...)` moves the
"current" pointer, for example to roll back.

## Layout

```
notebooks/flatfield_calibration.ipynb   the calibration notebook
src/flat_field/positions.py             Position dataclass, ESRF + DECTRIS EIGER2 loaders
src/flat_field/calibration.py           tutorial's extract_cpt, geometry prediction/refinement
src/flat_field/flatfield.py             mask, per-position gain map, median merge, QC metrics
src/flat_field/io.py                    EDF/HDF5/JSON bundle, metadata and provenance
src/flat_field/portal.py                versioned publish/promote/fetch on Girder
tests/                                  unit tests (synthetic gain recovery, EIGER loader, portal)
```

## Development

```bash
uv run pytest
uv run ruff check src tests
```

The code in `calibration.py` and the notebook are adapted from the pyFAI tutorial (pyFAI is MIT
licensed, © ESRF).
