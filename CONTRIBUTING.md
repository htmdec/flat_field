# Contributing

## One-time setup

```bash
git clone https://github.com/htmdec/flat_field.git
cd flat_field
uv sync                         # creates .venv from uv.lock (Python 3.12, incl. dev tools)
uv run nbstripout --install     # strip notebook outputs on every commit (per clone)
cp .env.example .env            # only if you will publish to data.htmdec.org
```

Put **your own** Girder API key in `.env`. `.env` is git-ignored: never commit it, and never paste
a key into a notebook.

## Making a change

1. Branch from `main`: `git switch -c short-description`.
2. Make the change. Run the notebook with `uv run jupyter lab`.
3. Check locally (CI runs the same steps):
   ```bash
   uv run ruff check src tests
   uv run pytest
   uv run nbstripout --verify --keep-id notebooks/*.ipynb
   ```
4. Push the branch and open a pull request. The **tests** workflow must pass before merging.
   It installs from `uv.lock`, then lints, checks that notebooks have no outputs, and runs
   the tests.

## Dependencies and `uv.lock`

- Add or remove packages with `uv add <pkg>` / `uv add --dev <pkg>` / `uv remove <pkg>`.
  Commit `pyproject.toml` and `uv.lock` together.
- Never edit `uv.lock` by hand. Upgrade on purpose with `uv lock --upgrade` (or
  `--upgrade-package <pkg>`), run the tests, then commit.
- On a merge conflict in `uv.lock`, take either side and run `uv lock` to regenerate it.
- CI uses `uv sync --locked`, so a PR fails if `uv.lock` doesn't match `pyproject.toml`.

## Notebooks

- Commit notebooks **without outputs**. The nbstripout hook does this for you; CI checks it.
- Keep settings in the cell tagged `parameters` (section 0) so runs can be configured
  without editing the code cells.
- Don't commit data or results: `output/`, `.edf` files and downloaded test data are ignored.
- Reusable logic belongs in `src/flat_field/` with a test in `tests/`. Keep notebook cells to
  calling it and plotting.

## Publishing calibrations

- Published flat-fields are immutable versions on data.htmdec.org. Publishing never overwrites,
  so test with `PUBLISH = False` first.
- `PROMOTE = True` changes which flat-field the workflows use. Only promote a calibration you
  have checked (quality-check numbers in section 9, maps in sections 8–9), and say so in your PR
  or lab notes. To roll back, promote an earlier version with `portal.promote_version(...)`.
- Commit your code changes *before* a calibration you intend to publish. The metadata records
  the git commit and marks it `-dirty` if there were uncommitted changes.
