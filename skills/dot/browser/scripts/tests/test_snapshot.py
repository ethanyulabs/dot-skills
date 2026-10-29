import json
import os

import pytest

from dbrowser_lib import snapshot

HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture
def ax_nodes():
    with open(os.path.join(HERE, "fixtures", "ax_example.json"), encoding="utf-8") as fh:
        return json.load(fh)["nodes"]


EXPECTED = """\
- heading "Example Domain" [level=1] [ref=e1]
- paragraph: This domain is for use in illustrative examples.
- paragraph:
  - link "More information..." [ref=e2]
- form:
  - textbox "Search" [active] [ref=e3]
  - checkbox "Remember" [ref=e4]
  - button "Go" [ref=e5]
- iframe "ad" [ref=e6] [cross-origin content not included]
- img "logo" [ref=e7]
- text: visible text inside an ignored wrapper"""


def test_build_text_and_refs(ax_nodes):
    text, refs = snapshot.build(ax_nodes)
    assert text == EXPECTED
    assert refs == {
        "e1": {"backend_node_id": 3, "role": "heading", "name": "Example Domain"},
        "e2": {"backend_node_id": 8, "role": "link", "name": "More information..."},
        "e3": {"backend_node_id": 11, "role": "textbox", "name": "Search"},
        "e4": {"backend_node_id": 12, "role": "checkbox", "name": "Remember"},
        "e5": {"backend_node_id": 13, "role": "button", "name": "Go"},
        "e6": {"backend_node_id": 14, "role": "iframe", "name": "ad"},
        "e7": {"backend_node_id": 15, "role": "img", "name": "logo"},
    }


def test_build_is_deterministic_and_depth_limited(ax_nodes):
    assert snapshot.build(ax_nodes) == snapshot.build(list(reversed(ax_nodes)))
    text, refs = snapshot.build(ax_nodes, max_depth=1)
    assert "- link" not in text and "- form: …" in text and "- paragraph: …" in text and "- textbox" not in text
    assert {r["role"] for r in refs.values()} == {"heading", "iframe", "img"}


def test_build_subtree_from_root_backend_id(ax_nodes):
    text, refs = snapshot.build(ax_nodes, root_backend_id=10)
    assert text == '- form:\n  - textbox "Search" [active] [ref=e1]\n  - checkbox "Remember" [ref=e2]\n  - button "Go" [ref=e3]'
    assert refs["e1"]["backend_node_id"] == 11


def test_states_and_values():
    nodes = [
        {"nodeId": "1", "ignored": False, "role": {"value": "RootWebArea"}, "childIds": ["2", "3", "4"], "backendDOMNodeId": 1},
        {"nodeId": "2", "ignored": False, "role": {"value": "textbox"}, "name": {"value": "Email"}, "value": {"value": "a@b.c"},
         "properties": [{"name": "focusable", "value": {"value": True}}], "childIds": [], "backendDOMNodeId": 2, "parentId": "1"},
        {"nodeId": "3", "ignored": False, "role": {"value": "checkbox"}, "name": {"value": "Agree"},
         "properties": [{"name": "checked", "value": {"value": "true"}}, {"name": "disabled", "value": {"value": True}}], "childIds": [], "backendDOMNodeId": 3, "parentId": "1"},
        {"nodeId": "4", "ignored": False, "role": {"value": "button"}, "name": {"value": "More"},
         "properties": [{"name": "expanded", "value": {"value": False}}, {"name": "pressed", "value": {"value": "mixed"}}], "childIds": [], "backendDOMNodeId": 4, "parentId": "1"},
    ]
    text, refs = snapshot.build(nodes)
    assert text == '- textbox "Email" [ref=e1]: a@b.c\n- checkbox "Agree" [checked] [disabled] [ref=e2]\n- button "More" [pressed=mixed] [ref=e3]'


def test_is_ref():
    assert snapshot.is_ref("e1") and snapshot.is_ref("e123")
    assert not snapshot.is_ref("e") and not snapshot.is_ref("button") and not snapshot.is_ref("css=e1") and not snapshot.is_ref("f1e2")


def test_boxes(ax_nodes):
    text, _ = snapshot.build(ax_nodes, boxes={8: (10, 20, 100, 30)})
    assert '- link "More information..." [ref=e2] [box=10,20,100,30]' in text


def test_build_on_a_recorded_arc_tree():
    """Accessibility.getFullAXTree as Arc 1.152 (Chrome 149) returned it for example.com on 2026-10-28."""
    with open(os.path.join(HERE, "fixtures", "ax_example_live.json"), encoding="utf-8") as fh:
        nodes = json.load(fh)["nodes"]
    text, refs = snapshot.build(nodes)
    lines = text.splitlines()
    assert lines[0].startswith("- paragraph: This domain is for use in documentation examples")
    assert lines[-1] == '- link "Learn more" [ref=e1]' and refs == {"e1": {"backend_node_id": refs["e1"]["backend_node_id"], "role": "link", "name": "Learn more"}}
    assert "InlineTextBox" not in text and "none" not in text and "RootWebArea" not in text
    assert sum(1 for l in lines if l.startswith("- paragraph:")) == 6
