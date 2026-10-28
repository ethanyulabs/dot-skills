import json
import urllib.error

import pytest

from darc_lib import DotArcError
from darc_lib import cdp_http as http
from conftest import FakeHTTP, page


@pytest.fixture
def fake(monkeypatch):
    f = FakeHTTP(pages=[page("A", "https://a.com/"), page("W", "chrome-extension://x/bg.html", "service_worker")])
    monkeypatch.setattr(http, "_fetch", f.fetch)
    return f


def test_version_and_unreachable(fake):
    assert http.version(9222)["Browser"].startswith("Chrome")
    fake.down = True
    with pytest.raises(DotArcError) as e:
        http.version(9222)
    assert e.value.code == "CDP_UNREACHABLE" and e.value.exit_code == 4
    assert "--remote-debugging-port=9222" in e.value.hint


def test_list_pages_filters_type(fake):
    assert [p["id"] for p in http.list_pages(9222)] == ["A"]
    assert http.find_target(9222, "A")["url"] == "https://a.com/"
    assert http.find_target(9222, "nope") is None


def test_activate(fake):
    assert http.activate(9222, "A") is True
    assert fake.activated == ["A"]


def test_wait_new_page_single_candidate(fake):
    before = {p["id"] for p in http.list_pages(9222)}
    fake.add_later(page("N", "https://example.com/"), after=4)
    clock = iter(x * 0.1 for x in range(100))
    r = http.wait_new_page(9222, before, "https://example.com", timeout_s=5, sleep=lambda s: None, clock=lambda: next(clock))
    assert r["target"]["id"] == "N" and r["candidates"] == [] and fake.list_calls >= 4


def test_wait_new_page_never_binds_an_unmatched_single_target(fake):
    """A tab the user opened meanwhile must not become our session (hard requirement a)."""
    before = {p["id"] for p in http.list_pages(9222)}
    fake.add_later(page("U", "https://user-opened.example/"), after=1)
    fake.add_later(page("N", "https://example.com/"), after=4)
    clock = iter(x * 0.1 for x in range(100))
    r = http.wait_new_page(9222, before, "https://example.com", timeout_s=5, sleep=lambda s: None, clock=lambda: next(clock))
    assert r["target"]["id"] == "N"
    before = {p["id"] for p in http.list_pages(9222)}
    fake.add_later(page("V", "https://other.example/"), after=1)
    t = iter([0.0, 0.5, 1.0, 1.5, 2.0, 2.5])
    r = http.wait_new_page(9222, before, "https://example.com", timeout_s=1, sleep=lambda s: None, clock=lambda: next(t))
    assert r["target"] is None and [c["id"] for c in r["candidates"]] == ["V"]


def test_wait_new_page_about_blank_is_not_a_match_until_it_navigates(fake):
    before = {p["id"] for p in http.list_pages(9222)}
    blank = page("B", "about:blank")
    fake.add_later(blank, after=1)
    calls = {"n": 0}
    def clock():
        calls["n"] += 1
        if calls["n"] == 3:
            blank["url"] = "https://example.com/"
        return calls["n"] * 0.1
    r = http.wait_new_page(9222, before, "https://example.com", timeout_s=5, sleep=lambda s: None, clock=clock)
    assert r["target"]["id"] == "B"


def test_wait_new_page_prefers_url_then_host(fake):
    before = {p["id"] for p in http.list_pages(9222)}
    fake.add_later(page("X", "https://other.com/"), after=1)
    fake.add_later(page("Y", "https://example.com/path?x=1"), after=1)
    fake.add_later(page("Z", "https://example.com/other"), after=1)
    r = http.wait_new_page(9222, before, "https://example.com/path", timeout_s=1, sleep=lambda s: None, clock=lambda: 0.0)
    assert r["target"]["id"] == "Y"
    before2 = {p["id"] for p in http.list_pages(9222)}
    fake.add_later(page("R", "https://login.example.com/sso"), after=1)
    fake.add_later(page("S", "https://other.com/2"), after=1)
    r = http.wait_new_page(9222, before2, "https://example.com/app", timeout_s=1, sleep=lambda s: None, clock=lambda: 0.0)
    assert r["target"]["id"] == "R"


def test_wait_new_page_ambiguous_and_timeout(fake):
    before = {p["id"] for p in http.list_pages(9222)}
    fake.add_later(page("X", "https://other.com/"), after=1)
    fake.add_later(page("Y", "https://third.com/"), after=1)
    t = iter([0.0, 0.5, 1.0, 1.5, 2.0])  # neither matches: they are reported as candidates only at the deadline
    r = http.wait_new_page(9222, before, "https://example.com", timeout_s=1, sleep=lambda s: None, clock=lambda: next(t))
    assert r["target"] is None and {c["id"] for c in r["candidates"]} == {"X", "Y"}
    before = {p["id"] for p in http.list_pages(9222)}
    fake.add_later(page("M1", "https://example.com/a"), after=1)
    fake.add_later(page("M2", "https://example.com/b"), after=1)
    r = http.wait_new_page(9222, before, "https://example.com/", timeout_s=1, sleep=lambda s: None, clock=lambda: 0.0)
    assert r["target"] is None and {c["id"] for c in r["candidates"]} == {"M1", "M2"}  # two matches: ambiguous at once
    before = {p["id"] for p in http.list_pages(9222)}
    t = iter([0.0, 0.5, 1.0, 1.5, 2.0])
    r = http.wait_new_page(9222, before, "https://example.com", timeout_s=1, sleep=lambda s: None, clock=lambda: next(t))
    assert r == {"target": None, "candidates": []}


def test_relaunch_instruction():
    r = http.relaunch_instruction(9333)
    assert "open -a Arc --args --remote-debugging-port=9333" in r["shell"]
    assert "quit" in r["shell"].lower() and r["zh"]
