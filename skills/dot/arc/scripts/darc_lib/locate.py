"""Turns a ref (`e12`) or a selector (`css=`, `xpath=`, `text=`, bare CSS) into a backendNodeId."""
from __future__ import annotations

import json

from . import DotArcError
from .snapshot import is_ref

FIND_TEXT_JS = """/*__darc_find_text__(%(needle)s)*/
(() => {
  const needle = %(needle)s;
  const norm = s => (s || "").replace(/\\s+/g, " ").trim();
  const all = Array.from(document.querySelectorAll("body *")).filter(el => !["SCRIPT", "STYLE", "NOSCRIPT"].includes(el.tagName));
  const pick = (test) => {
    const hits = all.filter(el => test(norm(el.innerText)));
    return hits.find(el => !hits.some(other => other !== el && el.contains(other))) || null;
  };
  return pick(t => t === needle) || pick(t => t.includes(needle));
})()"""


def _stale(msg: str) -> DotArcError:
    return DotArcError("REF_STALE", msg, "页面变了，先重新 `darc snapshot` 再用新的 ref", 5)


def _bid_of_node(cdp, node_id: int) -> int:
    return cdp.send("DOM.describeNode", {"nodeId": node_id})["node"]["backendNodeId"]


def _document(cdp) -> int:
    cdp.enable("DOM")
    return cdp.send("DOM.getDocument", {"depth": 0})["root"]["nodeId"]


def resolve_ref(cdp, sess: dict, ref: str) -> tuple[int, dict]:
    snap = sess.get("snapshot") or {}
    entry = (snap.get("refs") or {}).get(ref)
    if not entry:
        raise _stale(f"{ref} is not in the last snapshot of this session")
    loader = cdp.send("Page.getFrameTree")["frameTree"]["frame"].get("loaderId")
    if snap.get("loader_id") and loader != snap["loader_id"]:
        raise _stale("the page navigated since the last snapshot")
    try:
        cdp.send("DOM.describeNode", {"backendNodeId": entry["backend_node_id"]})
    except DotArcError as e:
        if e.code == "CDP_ERROR":
            raise _stale(f"{ref} no longer exists in the page")
        raise
    return entry["backend_node_id"], {"ref": ref, "role": entry.get("role"), "name": entry.get("name")}


def resolve_selector(cdp, spec: str) -> int:
    kind, _, value = spec.partition("=") if spec.startswith(("css=", "xpath=", "text=")) else ("css", "", spec)
    not_found = DotArcError("ELEMENT_NOT_FOUND", f"nothing matches {spec!r}", "take a `darc snapshot` and use a ref, or adjust the selector", 5)
    if kind == "css":
        root = _document(cdp)
        try:
            nid = cdp.send("DOM.querySelector", {"nodeId": root, "selector": value})["nodeId"]
        except DotArcError as e:
            if e.code == "CDP_ERROR":
                raise DotArcError("ELEMENT_NOT_FOUND", f"invalid or unmatched selector {value!r}: {e.message}", "", 5)
            raise
        if not nid:
            raise not_found
        return _bid_of_node(cdp, nid)
    if kind == "xpath":
        _document(cdp)
        found = cdp.send("DOM.performSearch", {"query": value})
        try:
            if not found.get("resultCount"):
                raise not_found
            nid = cdp.send("DOM.getSearchResults", {"searchId": found["searchId"], "fromIndex": 0, "toIndex": 1})["nodeIds"][0]
        finally:
            try:
                cdp.send("DOM.discardSearchResults", {"searchId": found["searchId"]})
            except DotArcError:
                pass
        return _bid_of_node(cdp, nid)
    if kind == "text":
        _document(cdp)
        needle = json.dumps(value, ensure_ascii=False)
        r = cdp.send("Runtime.evaluate", {"expression": FIND_TEXT_JS % {"needle": needle}, "returnByValue": False})
        obj = r.get("result", {})
        if not obj.get("objectId"):
            raise not_found
        nid = cdp.send("DOM.requestNode", {"objectId": obj["objectId"]})["nodeId"]
        return _bid_of_node(cdp, nid)
    raise DotArcError("BAD_ARGS", f"unknown selector kind {kind!r}", "use e12, css=..., xpath=... or text=...", 2)


def resolve(cdp, sess: dict, spec: str) -> tuple[int, dict]:
    """(backendNodeId, how it was found)."""
    if is_ref(spec):
        return resolve_ref(cdp, sess, spec)
    return resolve_selector(cdp, spec), {"selector": spec}
