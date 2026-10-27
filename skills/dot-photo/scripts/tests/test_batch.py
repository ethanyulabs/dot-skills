"""Folder input: every batchable command processes all photos under a directory."""
import json
import os
import re

import pytest
from PIL import Image

from dphoto_lib import cli
from dphoto_lib.imageio import content_sha1, save_png

from test_cli import run


@pytest.fixture
def album(tmp_path, jpeg_from, sky_ground, gradient_img):
    """album/ with two photos (one nested), plus everything a scan must skip."""
    jpeg_from(sky_ground, "album/sky.jpg")
    jpeg_from(gradient_img, "album/sub/grad.jpg")
    jpeg_from(gradient_img, "album/.hidden/h.jpg")
    jpeg_from(gradient_img, "album/sub/.dot.jpg")
    jpeg_from(gradient_img, "album/dot-photo/x.jpg")
    jpeg_from(gradient_img, "album/old.dot-photo/y.jpg")
    jpeg_from(gradient_img, "album/processed.jpg")
    (tmp_path / "album" / "notes.txt").write_text("not a photo")
    return str(tmp_path / "album")


def test_batch_scan_and_skips(capsys, album, dot_home):
    code, j = run(capsys, ["analyze", album, "--quiet"])
    assert code == 0 and j["ok"] and j["batch"] is True and j["action"] == "analyze"
    assert j["input"] == album
    assert os.path.dirname(j["out_dir"]) == os.path.join(dot_home, "runs")
    assert re.fullmatch(r"\d{8}-\d{6}(-\d+)?-album", os.path.basename(j["out_dir"]))
    assert j["output_root"] == os.path.join(dot_home, "output")
    photos = j["summary"]["photos"]
    assert [p["rel"] for p in photos] == ["sky.jpg", os.path.join("sub", "grad.jpg")]
    assert j["summary"]["total"] == 2 and j["summary"]["ok"] == 2
    h = content_sha1(os.path.join(album, "sub", "grad.jpg"))[:8]
    assert photos[1]["out_dir"] == os.path.join(dot_home, "output", f"grad-{h}")
    assert os.path.dirname(j["artifacts"]["batch"]) == j["out_dir"]
    assert photos[0]["status"] == "ok" and photos[0]["type"]["value"] == "landscape"
    assert os.path.isfile(os.path.join(photos[1]["out_dir"], "report.json"))
    assert j["artifacts"]["contact"] == []
    assert os.path.isfile(j["artifacts"]["batch"]) and os.path.isfile(j["artifacts"]["log"])
    full = json.load(open(j["artifacts"]["batch"], encoding="utf-8"))
    assert full["summary"]["photos"][0]["result"]["action"] == "analyze"


def test_batch_progress_goes_to_stderr_unless_quiet(capsys, album):
    cli.main(["analyze", album])
    err = capsys.readouterr().err
    assert "[1/2]" in err and "[2/2]" in err
    cli.main(["analyze", album, "--quiet"])
    assert capsys.readouterr().err == ""


def test_batch_failed_photo_counts(capsys, tmp_path, album):
    (tmp_path / "album" / "bad.jpg").write_bytes(b"not a jpeg")
    code, j = run(capsys, ["analyze", album, "--quiet"])
    assert code == 0 and j["ok"]
    assert j["summary"]["total"] == 3 and j["summary"]["ok"] == 2 and j["summary"]["failed"] == 1
    bad = [p for p in j["summary"]["photos"] if p["rel"] == "bad.jpg"][0]
    assert bad["status"] == "failed" and bad["error"]["code"] == "DECODE_FAILED"
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "a.jpg").write_bytes(b"nope")
    code, j = run(capsys, ["analyze", str(broken), "--quiet"])
    assert code == 5 and j["ok"] is False and j["error"]["code"] == "ALL_FAILED"
    assert j["summary"]["failed"] == 1


def test_batch_same_stem_different_content_gets_two_dirs(capsys, tmp_path, jpeg_from, gradient_img, dot_home):
    d = tmp_path / "dup"
    jpeg_from(gradient_img, "dup/a.jpg")
    save_png((gradient_img.rgb * 255).astype("uint8"), str(d / "a.png"))
    code, j = run(capsys, ["analyze", str(d), "--quiet"])
    assert code == 0
    outs = [p["out_dir"] for p in j["summary"]["photos"]]
    assert len(set(outs)) == 2 and all(os.path.isfile(os.path.join(o, "report.json")) for o in outs)
    assert all(os.path.basename(o).startswith("a-") for o in outs)


def test_batch_runs_twice_without_out_gets_two_run_dirs(capsys, album, dot_home):
    code, j1 = run(capsys, ["analyze", album, "--quiet"])
    code, j2 = run(capsys, ["analyze", album, "--quiet"])
    assert j1["out_dir"] != j2["out_dir"]
    assert not os.path.isfile(os.path.join(j2["out_dir"], "batch.prev.json"))


def test_run_dir_name_is_deterministic():
    import time
    from dphoto_lib.home import run_dir_name
    now = time.strptime("2026-10-27 14:30:12", "%Y-%m-%d %H:%M:%S")
    assert run_dir_name("/x/trip/", now=now) == "20261027-143012-trip"


def test_batch_no_recursive(capsys, album):
    code, j = run(capsys, ["analyze", album, "--quiet", "--no-recursive"])
    assert code == 0 and [p["rel"] for p in j["summary"]["photos"]] == ["sky.jpg"]


def test_batch_skip_existing(capsys, album):
    code, j = run(capsys, ["analyze", album, "--quiet"])
    assert code == 0 and j["summary"]["skipped"] == 0
    code, j = run(capsys, ["analyze", album, "--quiet", "--skip-existing"])
    assert code == 0 and j["ok"] and j["summary"]["skipped"] == 2 and j["summary"]["ok"] == 0
    assert all(p["status"] == "skipped" for p in j["summary"]["photos"])


def test_batch_skip_existing_with_a_failure_is_still_ok(capsys, tmp_path, album):
    run(capsys, ["analyze", album, "--quiet"])
    (tmp_path / "album" / "bad.jpg").write_bytes(b"nope")
    code, j = run(capsys, ["analyze", album, "--quiet", "--skip-existing"])
    assert code == 0 and j["ok"] and "error" not in j
    assert j["summary"]["skipped"] == 2 and j["summary"]["failed"] == 1 and j["summary"]["ok"] == 0


def test_batch_empty_dir(capsys, tmp_path):
    (tmp_path / "empty").mkdir()
    code, j = run(capsys, ["run", str(tmp_path / "empty")])
    assert code == 2 and j["ok"] is False and j["error"]["code"] == "NO_PHOTOS"


def test_batch_not_batchable(capsys, album):
    code, j = run(capsys, ["style", "extract", album])
    assert code == 2 and j["error"]["code"] == "BAD_ARGS"


def test_batch_run_contact_sheet_and_out(capsys, tmp_path, jpeg_from, sky_ground, skin_patch):
    jpeg_from(sky_ground, "shoot/sky.jpg")
    img, meta = skin_patch
    jpeg_from(img, "shoot/face.jpg")
    (tmp_path / "shoot" / "bad.jpg").write_bytes(b"nope")
    out = str(tmp_path / "results")
    code, j = run(capsys, ["run", str(tmp_path / "shoot"), "--out", out, "--quiet"])  # default exports incl. dating
    assert code == 0 and j["ok"] and j["out_dir"] == out and j["output_root"] == out
    photos = {p["rel"]: p for p in j["summary"]["photos"]}
    h = content_sha1(str(tmp_path / "shoot" / "sky.jpg"))[:8]
    assert photos["sky.jpg"]["out_dir"] == os.path.join(out, f"sky-{h}")
    assert photos["sky.jpg"]["type"]["used"] == "landscape"
    assert "NO_FACE" in photos["sky.jpg"]["needs_review"]
    assert j["summary"]["needs_review_counts"]["NO_FACE"] >= 1
    assert os.path.isfile(os.path.join(photos["sky.jpg"]["out_dir"], "export", "web.jpg"))
    contact = j["artifacts"]["contact"]
    assert contact == [os.path.join(out, "contact.jpg")] and os.path.isfile(contact[0])
    with Image.open(contact[0]) as im:
        assert im.width <= 1800 and im.height > 3 * 200
    # re-run keeps the previous round's batch files
    code, j = run(capsys, ["run", str(tmp_path / "shoot"), "--for", "web", "--out", out, "--quiet"])
    assert code == 0 and j["summary"]["ok"] == 2
    for name in ("batch.prev.json", "contact.prev.jpg"):
        assert os.path.isfile(os.path.join(out, name)), name


def test_batch_contact_sheet_pages(capsys, tmp_path, jpeg_from, gradient_img, dot_home):
    for i in range(13):
        jpeg_from(gradient_img, f"many/p{i:02d}.jpg")
    code, j = run(capsys, ["export", str(tmp_path / "many"), "--for", "web", "--quiet"])
    assert code == 0 and j["summary"]["ok"] == 13
    names = [os.path.basename(p) for p in j["artifacts"]["contact"]]
    assert names == ["contact.jpg", "contact-2.jpg"] and all(os.path.isfile(p) for p in j["artifacts"]["contact"])
    assert os.path.dirname(j["artifacts"]["contact"][0]) == j["out_dir"]
    assert j["out_dir"].startswith(os.path.join(dot_home, "runs"))


def test_batch_scan_excludes_the_home_itself(capsys, tmp_path, jpeg_from, gradient_img, dot_home):
    """Running a batch over a folder that contains DOT_HOME must not scan output/ or runs/."""
    jpeg_from(gradient_img, "dot/photo/output/old-12345678/processed.jpg")
    jpeg_from(gradient_img, "dot/photo/output/old-12345678/export/web.jpg")
    jpeg_from(gradient_img, "dot/pic.jpg")
    code, j = run(capsys, ["analyze", str(tmp_path / "dot"), "--quiet"])
    assert code == 0 and [p["rel"] for p in j["summary"]["photos"]] == ["pic.jpg"]


def test_is_processed_input_batch_root():
    assert cli.is_processed_input("/x/dot-photo/a.jpg") is False
    assert cli.is_processed_input("/x/dot-photo/a/processed.tif") is True
    assert cli.is_processed_input("/x/a.dot-photo/export/web.jpg") is True
