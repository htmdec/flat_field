import itertools
from pathlib import Path

import pytest

from flat_field import portal


class FakeGirder:
    """Just enough of girder_client.GirderClient for the portal module."""

    def __init__(self):
        self.ids = (f"id{i}" for i in itertools.count())
        self.folders = {"F": {"_id": "F", "meta": {}}}
        self.items = {}
        self.files = {}

    def listItem(self, folder_id, name=None):
        for it in list(self.items.values()):
            if it["folderId"] == folder_id and (name is None or it["name"] == name):
                yield it

    def createItem(self, folder_id, name, description=""):
        it = {"_id": next(self.ids), "folderId": folder_id, "name": name, "meta": {}}
        self.items[it["_id"]] = it
        return it

    def uploadFileToItem(self, item_id, path):
        fid = next(self.ids)
        self.files[fid] = {"_id": fid, "itemId": item_id, "name": Path(path).name,
                           "bytes": Path(path).read_bytes()}

    def addMetadataToItem(self, item_id, meta):
        self.items[item_id]["meta"].update(meta)

    def getFolder(self, folder_id):
        return self.folders[folder_id]

    def addMetadataToFolder(self, folder_id, meta):
        self.folders[folder_id]["meta"].update(meta)

    def getItem(self, item_id):
        return self.items[item_id]

    def listFile(self, item_id):
        return [f for f in self.files.values() if f["itemId"] == item_id]

    def downloadFile(self, file_id, path):
        Path(path).write_bytes(self.files[file_id]["bytes"])

    def delete(self, path):
        self.items.pop(path.split("/")[-1], None)


def _files(tmp_path, tag):
    p = tmp_path / f"{tag}.edf"
    p.write_bytes(tag.encode())
    return [p]


def test_publish_promote_resolve_fetch(tmp_path):
    gc = FakeGirder()
    r1 = portal.publish_flatfield(gc, "F", _files(tmp_path, "a"), {"stats": {"x.y": 1}},
                                  "E-02-0375", 24.21, "2026-11-19T100000Z", promote=True)
    r2 = portal.publish_flatfield(gc, "F", _files(tmp_path, "b"), {}, "E-02-0375", 24.21,
                                  "2026-11-20T100000Z", promote=False)
    assert r1["promoted"] and not r2["promoted"]
    assert gc.items[r1["item_id"]]["meta"]["stats"] == {"x_y": 1}  # dots made Girder-safe
    assert portal.resolve_flatfield(gc, "F", "E-02-0375")["_id"] == r1["item_id"]
    assert portal.resolve_flatfield(gc, "F", "E-02-0375", "latest")["_id"] == r2["item_id"]
    by_label = portal.resolve_flatfield(gc, "F", "E-02-0375", "2026-11-19T100000Z")
    assert by_label["_id"] == r1["item_id"]
    got = portal.fetch_flatfield(gc, "F", "E-02-0375", tmp_path / "dl")
    assert got["paths"]["a.edf"].read_bytes() == b"a"
    portal.promote_version(gc, "F", r2["item_id"], "E-02-0375", "2026-11-20T100000Z")
    assert portal.resolve_flatfield(gc, "F", "E-02-0375")["_id"] == r2["item_id"]


def test_versions_are_immutable(tmp_path):
    gc = FakeGirder()
    args = (gc, "F", _files(tmp_path, "a"), {}, "D", 24.21, "v1")
    portal.publish_flatfield(*args)
    with pytest.raises(portal.PortalError):
        portal.publish_flatfield(*args)


def test_no_current(tmp_path):
    with pytest.raises(portal.PortalError):
        portal.resolve_flatfield(FakeGirder(), "F", "D")
