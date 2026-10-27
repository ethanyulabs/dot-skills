import json
import os
import re
import subprocess
import sys

import pytest

from dphoto_lib import cli

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(capsys, argv):
    code = cli.main(argv)
    out = capsys.readouterr().out
    lines = [l for l in out.splitlines() if l.strip()]
    assert len(lines) == 1, out
    return code, json.loads(lines[0])


def test_selftest(capsys):
    code, j = run(capsys, ["selftest"])
    assert code == 0 and j["ok"] and j["haar"] and j["imagecms"]
    assert "neutral" in j["presets"]


def test_deps_in_sync():
    def deps(name):
        txt = open(os.path.join(SCRIPTS, name), encoding="utf-8").read()
        block = txt.split("# ///")[1]
        return set(re.findall(r'"([^"]+)"', block))
    a, b = deps("dphoto.py"), deps("run_tests.py")
    assert a <= b and (b - a) == {"pytest>=8"}


def test_missing_file(capsys):
    code, j = run(capsys, ["info", "/no/such/file.jpg"])
    assert code == 3 and j["ok"] is False and j["error"]["code"] == "INPUT_NOT_FOUND"


def test_bad_args(capsys):
    code, j = run(capsys, ["portrait"])
    assert code == 2 and j["ok"] is False


def test_info_and_analyze(capsys, jpeg_from, sky_ground, tmp_path):
    p = jpeg_from(sky_ground, "sky.jpg")
    code, j = run(capsys, ["info", p])
    assert code == 0 and j["size"] == [1200, 800] and j["suggested_type"]["value"] == "landscape"
    out = str(tmp_path / "out")
    code, j = run(capsys, ["analyze", p, "--out", out])
    assert code == 0 and os.path.isfile(j["artifacts"]["analysis"]) and os.path.isfile(j["artifacts"]["report"])
    assert j["summary"]["type"]["value"] == "landscape"


def test_style_extract_and_apply(capsys, jpeg_from, warm_cast_img, gradient_img, tmp_path):
    ref = jpeg_from(warm_cast_img, "ref.jpg")
    tgt = jpeg_from(gradient_img, "tgt.jpg")
    code, j = run(capsys, ["style", "extract", ref, "--name", "warm", "--out", str(tmp_path / "ref.out")])
    assert code == 0 and j["action"] == "style.extract"
    style_path = j["artifacts"]["style"]
    assert os.path.isfile(style_path) and j["summary"]["color"]["temperature"] > 0
    out = str(tmp_path / "tgt.out")
    code, j = run(capsys, ["style", "apply", tgt, "--style", style_path, "--out", out, "--quiet"])
    assert code == 0 and j["action"] == "style.apply"
    for k in ("processed", "processed_jpg", "compare", "report", "style", "analysis"):
        assert os.path.isfile(j["artifacts"][k]), k
    assert j["summary"]["mode"] == "hybrid"
    code, j = run(capsys, ["style", "apply", tgt, "--style", "nope", "--out", out])
    assert code == 2 and j["error"]["code"] == "STYLE_NOT_FOUND"


def test_default_out_dir(capsys, jpeg_from, gradient_img):
    p = jpeg_from(gradient_img, "g.jpg")
    code, j = run(capsys, ["analyze", p, "--quiet"])
    assert code == 0 and j["out_dir"] == os.path.splitext(p)[0] + ".dot-photo"


@pytest.mark.skipif(not os.environ.get("DOT_PHOTO_SUBPROCESS"), reason="set DOT_PHOTO_SUBPROCESS=1 to run the uv entry")
def test_entry_subprocess():
    r = subprocess.run(["uv", "run", "--script", os.path.join(SCRIPTS, "dphoto.py"), "selftest"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and json.loads(r.stdout.strip().splitlines()[-1])["ok"]


def test_portrait_cli(capsys, jpeg_from, skin_patch, tmp_path):
    img, meta = skin_patch
    p = jpeg_from(img, "skin.jpg")
    x, y, w, h = meta["face_box"]
    out = str(tmp_path / "p.out")
    code, j = run(capsys, ["portrait", p, "--face", f"{x},{y},{w},{h}", "--out", out, "--quiet", "--debug"])
    assert code == 0 and j["action"] == "portrait"
    for k in ("processed", "processed_jpg", "compare", "report", "analysis"):
        assert os.path.isfile(j["artifacts"][k]), k
    assert j["summary"]["metrics"]["blemishes_removed"] >= 6
    assert os.path.isfile(os.path.join(out, "masks", "skin.png"))
    assert j["summary"]["faces"][0]["kind"] == "manual"
    code, j = run(capsys, ["portrait", p, "--face", "3", "--out", out, "--quiet"])
    assert code == 2 and j["error"]["code"] == "BAD_FACE"


def test_landscape_and_export_cli(capsys, jpeg_from, sky_ground, tmp_path):
    p = jpeg_from(sky_ground, "sky.jpg")
    out = str(tmp_path / "l.out")
    code, j = run(capsys, ["landscape", p, "--out", out, "--quiet", "--dehaze", "0.3"])
    assert code == 0 and j["summary"]["params_used"]["dehaze"] == 0.3
    assert os.path.isfile(j["artifacts"]["processed"])
    code, j = run(capsys, ["export", j["artifacts"]["processed"], "--for", "print,web", "--paper", "A4",
                           "--finish", "glossy", "--out", out, "--quiet"])
    assert code == 0 and set(j["artifacts"]["exports"]) == {"print", "web"}
    assert j["summary"]["params_used"]["dating_retouch"] is False  # input lives in a .dot-photo dir
    assert os.path.isfile(j["artifacts"]["compare"])
    code, j = run(capsys, ["export", p, "--for", "tiktok", "--out", out, "--quiet"])
    assert code == 2 and j["error"]["code"] == "BAD_TARGET"


def test_run_cli(capsys, jpeg_from, sky_ground, skin_patch, tmp_path):
    p = jpeg_from(sky_ground, "sky.jpg")
    out = str(tmp_path / "run.out")
    code, j = run(capsys, ["run", p, "--out", out, "--quiet"])
    assert code == 0 and j["action"] == "run"
    assert j["summary"]["type"]["used"] == "landscape"
    ex = j["artifacts"]["exports"]
    assert {"print", "web", "dating_1x1", "dating_4x5"} <= set(ex)
    assert all(os.path.isfile(v) for v in ex.values())
    assert any(r["code"] == "NO_FACE" for r in j["needs_review"])
    assert os.path.isfile(j["artifacts"]["style"]) and os.path.isfile(j["artifacts"]["compare"])
    img, meta = skin_patch
    p2 = jpeg_from(img, "skin.jpg")
    x, y, w, h = meta["face_box"]
    out2 = str(tmp_path / "run2.out")
    code, j = run(capsys, ["run", p2, "--type", "portrait", "--face", f"{x},{y},{w},{h}", "--for", "dating",
                           "--out", out2, "--quiet"])
    assert code == 0 and j["summary"]["type"]["used"] == "portrait"
    assert set(j["artifacts"]["exports"]) == {"dating_1x1", "dating_4x5"}
    assert j["summary"]["style"] == "clean-portrait"
    rep = json.load(open(j["artifacts"]["report"], encoding="utf-8"))
    assert rep["analysis"]["size"] == [1200, 1200]


def test_compare_cli(capsys, jpeg_from, sky_ground, gradient_img, tmp_path):
    a = jpeg_from(sky_ground, "a.jpg")
    b = jpeg_from(sky_ground.copy_with(sky_ground.rgb * 0.8), "b.jpg")
    out = str(tmp_path / "cmp.jpg")
    code, j = run(capsys, ["compare", a, b, "--out", out, "--focus", "100,100,300,200"])
    assert code == 0 and os.path.isfile(j["artifacts"]["compare"])
    g = jpeg_from(gradient_img, "g.jpg")
    code, j = run(capsys, ["compare", a, g, "--out", out])
    assert code == 2 and j["error"]["code"] == "SIZE_MISMATCH"


def test_rerun_keeps_previous_round_and_writes_focus_and_log(capsys, jpeg_from, sky_ground, tmp_path):
    p = jpeg_from(sky_ground, "sky.jpg")
    out = str(tmp_path / "rounds")
    code, j = run(capsys, ["landscape", p, "--out", out, "--quiet"])
    assert code == 0 and os.path.isfile(j["artifacts"]["focus"])
    assert 0 < j["summary"]["focus_zoom"] <= 1.0
    assert "style" in j["summary"]["params_used"]
    assert os.path.isfile(os.path.join(out, "log.txt"))
    assert "analyzed" in open(os.path.join(out, "log.txt"), encoding="utf-8").read()
    code, j = run(capsys, ["landscape", p, "--out", out, "--quiet", "--dehaze", "0.4"])
    assert code == 0
    for name in ("compare.prev.jpg", "focus.prev.jpg", "report.prev.json"):
        assert os.path.isfile(os.path.join(out, name)), name


def test_run_summary_params_used_and_report_sections(capsys, jpeg_from, sky_ground, tmp_path):
    p = jpeg_from(sky_ground, "sky.jpg")
    out = str(tmp_path / "pu")
    code, j = run(capsys, ["run", p, "--out", out, "--quiet", "--for", "web"])
    pu = j["summary"]["params_used"]
    assert pu["style"]["name"] == "neutral" and pu["style"]["strength"] == 1.0
    assert pu["landscape"]["dehaze"] == 0.15 and pu["export"]["paper"] == "4x6"
    rep = json.load(open(j["artifacts"]["report"], encoding="utf-8"))
    assert "style" in rep and "type_info" in rep and "analysis" in rep
