import numpy as np

from dphoto_lib import color


def test_srgb_linear_roundtrip():
    x = np.linspace(0, 1, 101, dtype=np.float32)
    assert np.allclose(color.linear_to_srgb(color.srgb_to_linear(x)), x, atol=1e-4)


def test_curve_lut_identity_and_monotone():
    lut = color.build_curve_lut([[0, 0], [255, 255]])
    assert np.allclose(lut, color.identity_lut(len(lut)), atol=1e-6)
    lut2 = color.build_curve_lut([[0, 0], [64, 40], [128, 140], [192, 210], [255, 255]])
    assert np.all(np.diff(lut2) >= -1e-6)
    assert lut2[0] == 0 and abs(lut2[-1] - 1) < 1e-6


def test_s_curve_monotone_and_direction():
    for c in (-100, -50, 0, 50, 100):
        lut = color.s_curve_lut(c)
        assert np.all(np.diff(lut) >= -1e-6), c
    hi = color.s_curve_lut(100)
    assert hi[int(0.25 * 4095)] < 0.25 and hi[int(0.75 * 4095)] > 0.75


def test_blacks_whites():
    crush = color.blacks_whites_lut(-100, 0)
    assert crush[int(0.05 * 4095)] < 0.02
    lift = color.blacks_whites_lut(100, 0)
    assert lift[0] > 0.05
    white_up = color.blacks_whites_lut(0, 100)
    assert white_up[int(0.9 * 4095)] > 0.95
    for b, w in ((-100, 100), (100, -100)):
        assert np.all(np.diff(color.blacks_whites_lut(b, w)) >= -1e-6)


def test_apply_lut_luma_keeps_hue():
    rgb = np.full((4, 4, 3), (0.6, 0.3, 0.2), np.float32)
    out = color.apply_lut_luma(rgb, color.s_curve_lut(60))
    h0 = color.rgb_to_hsv(rgb)[0, 0, 0]
    h1 = color.rgb_to_hsv(out)[0, 0, 0]
    assert abs(h0 - h1) < 1.0


def test_temperature_gains_direction():
    g = color.temperature_tint_gains(50, 0)
    assert g[0] > 1 > g[2] and abs(g[1] - 1) < 1e-6
    g = color.temperature_tint_gains(0, 50)
    assert g[1] < 1


def test_guided_filter_matches_fallback_and_preserves_edges():
    rng = np.random.default_rng(0)
    img = np.zeros((128, 128), np.float32)
    img[:, 64:] = 1.0
    noisy = np.clip(img + rng.normal(0, 0.05, img.shape).astype(np.float32), 0, 1)
    a = color.guided_filter(noisy, noisy, 6, 0.01)
    b = color._guided_filter_np(noisy, noisy, 6, 0.01)
    assert np.abs(a - b).mean() < 0.01
    # edge stays sharp: left stays near 0, right near 1 within a few px of the edge
    assert a[:, 58].mean() < 0.15 and a[:, 70].mean() > 0.85
    # noise reduced on flat areas
    assert a[:, :50].std() < noisy[:, :50].std() * 0.5


def test_p3_to_srgb_neutral_stays_neutral():
    gray = np.full((2, 2, 3), 0.5, np.float32)
    out = color.p3_to_srgb(gray)
    assert np.allclose(out, 0.5, atol=0.01)
    red = np.zeros((1, 1, 3), np.float32)
    red[..., 0] = 1
    out = color.p3_to_srgb(red)
    assert out[0, 0, 0] > 0.99 and out[0, 0, 1] < 0.05
