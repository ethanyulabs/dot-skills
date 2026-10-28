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


def test_default_out_dir(capsys, jpeg_from, gradient_img, dot_home):
    from dphoto_lib.imageio import content_sha1
    p = jpeg_from(gradient_img, "g.jpg")
    code, j = run(capsys, ["analyze", p, "--quiet"])
    assert code == 0 and j["out_dir"] == os.path.join(dot_home, "output", f"g-{content_sha1(p)[:8]}")
    src = json.load(open(os.path.join(j["out_dir"], "source.json"), encoding="utf-8"))
    assert src["paths"] == [p] and src["sha1"] == content_sha1(p) and src["size"] == os.path.getsize(p)
    # a copy with another name lands in its own directory; a copy with the same name shares it
    import shutil
    copy_dir = os.path.join(os.path.dirname(p), "elsewhere")
    os.makedirs(copy_dir)
    same = shutil.copy(p, os.path.join(copy_dir, "g.jpg"))
    code, j2 = run(capsys, ["analyze", same, "--quiet"])
    assert code == 0 and j2["out_dir"] == j["out_dir"]
    src = json.load(open(os.path.join(j["out_dir"], "source.json"), encoding="utf-8"))
    assert src["paths"] == [p, same]
    assert os.path.isfile(os.path.join(j["out_dir"], "report.prev.json"))


def test_export_of_a_processed_file_stays_in_its_output_dir(capsys, jpeg_from, sky_ground, dot_home):
    p = jpeg_from(sky_ground, "sky.jpg")
    code, j = run(capsys, ["landscape", p, "--quiet"])
    assert code == 0 and j["out_dir"].startswith(os.path.join(dot_home, "output"))
    code, j2 = run(capsys, ["export", j["artifacts"]["processed"], "--for", "web", "--quiet"])
    assert code == 0 and j2["out_dir"] == j["out_dir"]
    assert j2["summary"]["params_used"]["dating_retouch"] is False


def test_is_processed_input_knows_the_home_output_dir(dot_home):
    assert cli.is_processed_input(os.path.join(dot_home, "output", "x-1234abcd", "export", "web.jpg")) is True
    assert cli.is_processed_input(os.path.join(dot_home, "output2", "x.jpg")) is False
    assert cli.is_processed_input(os.path.join(dot_home, "styles", "x.json")) is False


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
    assert j["summary"]["params_used"]["dating_retouch"] is False  # processed.* is already retouched
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


# ---------------------------------------------------------------- user styles

def test_style_extract_with_name_saves_a_user_style(capsys, jpeg_from, warm_cast_img, gradient_img, dot_home):
    ref = jpeg_from(warm_cast_img, "ref.jpg")
    code, j = run(capsys, ["style", "extract", ref, "--name", "warm-look", "--quiet"])
    assert code == 0 and j["artifacts"]["style_user"] == os.path.join(dot_home, "styles", "warm-look.json")
    assert os.path.isfile(j["artifacts"]["style_user"]) and j["summary"]["saved_as"] == "warm-look"
    code, j = run(capsys, ["style", "extract", ref, "--name", "warm-look", "--quiet"])
    assert code == 2 and j["error"]["code"] == "STYLE_EXISTS"
    code, j = run(capsys, ["style", "extract", ref, "--name", "warm-look", "--force", "--quiet"])
    assert code == 0
    code, j = run(capsys, ["style", "extract", ref, "--name", "neutral", "--quiet"])
    assert code == 2 and j["error"]["code"] == "STYLE_NAME_RESERVED"
    code, j = run(capsys, ["style", "extract", ref, "--name", "none", "--quiet"])
    assert code == 2 and j["error"]["code"] == "STYLE_NAME_RESERVED"
    code, j = run(capsys, ["style", "extract", ref, "--name", "a/b", "--quiet"])
    assert code == 2 and j["error"]["code"] == "STYLE_NAME_INVALID"
    code, j = run(capsys, ["style", "extract", ref, "--quiet"])
    assert code == 0 and "style_user" not in j["artifacts"]
    tgt = jpeg_from(gradient_img, "tgt.jpg")
    code, j = run(capsys, ["style", "apply", tgt, "--style", "warm-look", "--quiet"])
    assert code == 0 and j["summary"]["style"] == "warm-look"
    code, j = run(capsys, ["style", "list"])
    assert code == 0 and j["action"] == "style.list" and j["styles_dir"] == os.path.join(dot_home, "styles")
    assert [s["name"] for s in j["user"]] == ["warm-look"] and j["user"][0]["valid"] is True
    assert "neutral" in [s["name"] for s in j["builtin"]]


# ---------------------------------------------------------------- config.json

def _write_config(dot_home, defaults):
    os.makedirs(dot_home, exist_ok=True)
    path = os.path.join(dot_home, "config.json")
    json.dump({"schema": "dot-photo/config/1", "defaults": defaults}, open(path, "w", encoding="utf-8"))
    return path


def test_config_defaults_apply_below_the_command_line(capsys, jpeg_from, skin_patch, dot_home):
    img, meta = skin_patch
    p = jpeg_from(img, "skin.jpg")
    x, y, w, h = meta["face_box"]
    face = f"{x},{y},{w},{h}"
    _write_config(dot_home, {"portrait": {"skin-strength": 0.4, "blemish": "off"}})
    code, j = run(capsys, ["portrait", p, "--face", face, "--quiet"])
    assert code == 0 and j["summary"]["params_used"]["skin_strength"] == 0.4
    assert j["summary"]["params_used"]["blemish"] is False
    assert j["config_applied"] == {"portrait": {"skin-strength": 0.4, "blemish": "off"}}
    code, j = run(capsys, ["portrait", p, "--face", face, "--skin-strength", "0.7", "--quiet"])
    assert code == 0 and j["summary"]["params_used"]["skin_strength"] == 0.7
    assert j["config_applied"]["portrait"]["skin-strength"] == 0.4  # what the config holds, even when overridden


def test_config_run_takes_every_section(capsys, jpeg_from, sky_ground, dot_home):
    p = jpeg_from(sky_ground, "sky.jpg")
    _write_config(dot_home, {"landscape": {"dehaze": 0.3}, "export": {"for": "web", "paper": "5x7"},
                             "run": {"style": "none"}, "portrait": {"skin-strength": 0.4}})
    code, j = run(capsys, ["run", p, "--quiet"])
    assert code == 0
    pu = j["summary"]["params_used"]
    assert pu["landscape"]["dehaze"] == 0.3 and pu["export"]["paper"] == "5x7" and pu["style"] is None
    assert set(j["artifacts"]["exports"]) == {"web"}
    assert set(j["config_applied"]) == {"landscape", "export", "run", "portrait"}


def test_config_unknown_or_common_keys_warn(capsys, jpeg_from, gradient_img, dot_home):
    p = jpeg_from(gradient_img, "g.jpg")
    _write_config(dot_home, {"landscape": {"dehaze": 0.3, "bogus": 1, "quiet": True, "sky": "sideways"},
                             "nonsense": {"a": 1}})
    code, j = run(capsys, ["landscape", p, "--quiet"])
    assert code == 0 and j["summary"]["params_used"]["dehaze"] == 0.3
    text = " ".join(j["warnings"])
    assert "bogus" in text and "quiet" in text and "sideways" in text and "nonsense" in text
    assert j["config_applied"] == {"landscape": {"dehaze": 0.3}}


def test_config_broken_json_warns_but_the_command_runs(capsys, jpeg_from, gradient_img, dot_home):
    os.makedirs(dot_home, exist_ok=True)
    open(os.path.join(dot_home, "config.json"), "w").write("{broken")
    p = jpeg_from(gradient_img, "g.jpg")
    code, j = run(capsys, ["analyze", p, "--quiet"])
    assert code == 0 and any("config.json" in w for w in j["warnings"])
    code, j = run(capsys, ["config", "show"])
    assert code == 2 and j["error"]["code"] == "CONFIG_INVALID"
    code, j = run(capsys, ["config", "set", "portrait", "skin-strength=0.4"])
    assert code == 2 and j["error"]["code"] == "CONFIG_INVALID"
    assert open(os.path.join(dot_home, "config.json")).read() == "{broken"


def test_config_set_show_unset_round_trip(capsys, dot_home):
    code, j = run(capsys, ["config", "show"])
    assert code == 0 and j["action"] == "config.show" and j["dot_home"] == os.path.dirname(dot_home)
    assert j["config"]["defaults"] == {} and j["config_path"] == os.path.join(dot_home, "config.json")
    code, j = run(capsys, ["config", "set", "portrait", "skin-strength=0.4", "blemish=off"])
    assert code == 0 and j["defaults"]["portrait"] == {"skin-strength": 0.4, "blemish": "off"}
    assert json.load(open(j["config_path"]))["defaults"]["portrait"]["skin-strength"] == 0.4
    code, j = run(capsys, ["config", "set", "export", "for=print,web", "tiff16=true"])
    assert code == 0 and j["defaults"]["export"] == {"for": "print,web", "tiff16": True}
    code, j = run(capsys, ["config", "set", "portrait", "blemish=maybe"])
    assert code == 2 and j["error"]["code"] == "CONFIG_BAD_VALUE"
    code, j = run(capsys, ["config", "set", "portrait", "dehaze=1"])
    assert code == 2 and j["error"]["code"] == "CONFIG_BAD_KEY"
    code, j = run(capsys, ["config", "set", "kitchen", "a=1"])
    assert code == 2 and j["error"]["code"] == "CONFIG_BAD_SECTION"
    code, j = run(capsys, ["config", "unset", "portrait", "blemish"])
    assert code == 0 and j["defaults"]["portrait"] == {"skin-strength": 0.4}
    code, j = run(capsys, ["config", "unset", "portrait"])
    assert code == 0 and "portrait" not in j["defaults"]
    code, j = run(capsys, ["selftest"])
    assert code == 0 and j["dot_home"] == os.path.dirname(dot_home) and j["config_ok"] is True and j["user_styles"] == []
