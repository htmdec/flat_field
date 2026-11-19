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

> **Measuring on MAXIMA?** Read the [MAXIMA measurement recipe](#maxima-measurement-recipe) at
> the bottom of this page before collecting data. It covers the scatterer, beamstop, positions,
> geometry and settings that differ from the synchrotron tutorial.

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

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: `uv sync`, then `uv run nbstripout --install`
once per clone, and check with `uv run ruff check src tests` and `uv run pytest`. A GitHub
Actions workflow (`.github/workflows/tests.yml`) runs the same checks on every pull request.

The code in `calibration.py` and the notebook are adapted from the pyFAI tutorial (pyFAI is MIT
licensed, © ESRF).

## MAXIMA measurement recipe

The method was designed for transmission diffraction, which is how MAXIMA works: the direct beam
lands on the EIGER2, which sits about 85 mm from the sample and is tilted about 3.6°. The tutorial
data come from a synchrotron, where the detector itself was moved between exposures. On MAXIMA
the detector and beamstop are fixed and only the sample moves, so a few things are done
differently.

1. **Scatterer: a flat plate, square to the beam.** A tilted plate absorbs more on one side than
   the other, and that unevenness ends up in the flat-field. Don't use a capillary.
2. **Low-element material that does not fluoresce above the 12.1 keV threshold.** Glassy carbon,
   acrylic (PMMA), Kapton or ordinary glass are suitable. Avoid anything containing elements whose
   fluorescence lines lie above about 12 keV: that would add a second photon energy to the signal.
3. **Mask the beamstop.** On MAXIMA the beamstop shadow always covers the same pixels, so moving
   between positions cannot fill it in, and the automatic mask (negative pixels plus the DECTRIS
   `pixel_mask`) does not include it. Shadowed pixels must be masked explicitly; the notebook
   does not do this automatically yet.
4. **Positions: vary the sample-to-detector distance, not the sideways position.** Moving the
   sample sideways leaves the pattern in the same place on the detector, because the pattern
   stays centred on the beam. Changing the distance moves the rings inwards or outwards. One
   position already gives a full map. Extra positions average down the noise and remove artefacts
   that belong to one setup (holder scatter, stray crystallites in the scatterer). Use at least
   `MIN_VALID` positions (default 5), or lower `MIN_VALID` to match.
5. **Geometry: give every position a `.poni`** (e.g. from a calibrant exposure at that distance,
   as produced by the MAXIMA Dagster pipeline) **or a calibrant image** for refinement. Keep the
   detector rotations free in the fit (`fix_rotations=False`, the MAXIMA default), because the
   detector is tilted.
6. **Counts: expose long.** The per-pixel precision is about 1/√counts. Aim for ~2,500 counts
   per pixel (~2 %) to find bad pixels and check the factory flatfield, and ~10,000 (~1 %) for a
   correction map. Several exposures at the same position can be summed.
7. **Settings: same source, voltage, current, energy and threshold as the experiments the
   correction is for.** The In source is not a single energy (Ga lines are removed by the
   threshold, but some of the continuous spectrum gets through). The flat-field you measure is
   the detector's response to that spectrum, which is what your real data see. Re-measure after
   any change to the source, threshold, detector firmware or geometry, and about quarterly.
8. **Polarization: `0.0`** (unpolarized lab source). Check it with `guess_polarization` in
   section 6 of the notebook.
9. **Remember it is a residual correction.** The EIGER2 already applies DECTRIS's factory
   flatfield, so this map corrects what that leaves behind. In processing, apply it with
   `flat=` **together with** `mask=pixel_mask != 0`.
10. **Check before promoting.** In the quality check (section 9) the *pixel-scale* spread should
    drop to near the counting-noise level. Look at the merged map (section 9) for structure that
    follows the beamstop, holder or sample edges rather than the detector chips. Only then publish
    with `PROMOTE = True`.

