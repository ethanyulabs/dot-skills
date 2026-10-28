import pytest

from darc_lib import DotArcError, locate, session as sessmod
from conftest import FakeSession


def sess_with_refs(loader="L1"):
    s = sessmod.create("k", 9222, {"title": "agent", "id": "S", "source": "flag"},
                       {"arc_id": "T", "target_id": "P", "ws_url": "ws://x", "url": "https://example.com/", "title": "E"})
    sessmod.set_refs(s, url="https://example.com/", root="body", loader_id=loader,
                     refs={"e2": {"backend_node_id": 8, "role": "link", "name": "More information..."}})
    return s


def test_ref_resolves_to_backend_id():
    cdp = FakeSession()
    assert locate.resolve(cdp, sess_with_refs(), "e2") == (8, {"ref": "e2", "role": "link", "name": "More information..."})


def test_ref_stale_when_loader_changed_or_node_gone_or_unknown():
    cdp = FakeSession(loader_id="L9")
    with pytest.raises(DotArcError) as e:
        locate.resolve(cdp, sess_with_refs(), "e2")
    assert e.value.code == "REF_STALE" and e.value.exit_code == 5 and "snapshot" in e.value.hint
    cdp = FakeSession()
    cdp.known.discard(8)
    with pytest.raises(DotArcError) as e:
        locate.resolve(cdp, sess_with_refs(), "e2")
    assert e.value.code == "REF_STALE"
    with pytest.raises(DotArcError) as e:
        locate.resolve(cdp, sess_with_refs(), "e7")
    assert e.value.code == "REF_STALE"
    s = sess_with_refs(); s["snapshot"] = None
    with pytest.raises(DotArcError) as e:
        locate.resolve(cdp, s, "e2")
    assert e.value.code == "REF_STALE"


def test_css_xpath_text_selectors():
    cdp = FakeSession()
    s = sess_with_refs()
    assert locate.resolve(cdp, s, "button#go")[0] == 13
    assert locate.resolve(cdp, s, "css=input[name=q]")[0] == 11
    assert locate.resolve(cdp, s, "xpath=//a")[0] == 8
    assert locate.resolve(cdp, s, "text=More information...")[0] == 8
    assert locate.resolve(cdp, s, "text=Go") == (13, {"selector": "text=Go"})
    for missing in ("css=nope", "xpath=//nope", "text=nope"):
        with pytest.raises(DotArcError) as e:
            locate.resolve(cdp, s, missing)
        assert e.value.code == "ELEMENT_NOT_FOUND" and e.value.exit_code == 5
