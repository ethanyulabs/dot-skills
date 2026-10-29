"""Accessibility snapshot: Accessibility.getFullAXTree → an indented outline with stable element refs.

Pure functions: `build` takes the raw node list so it can be tested on recorded trees. Refs are
`e1..eN` in document order; each maps to a backendDOMNodeId, which is stable for the lifetime of the
document, so a later process can act on it after checking the frame's loaderId (see locate.py).
"""
from __future__ import annotations

import re

REF_RE = re.compile(r"e\d+")

INTERACTIVE = {
    "link", "button", "textbox", "searchbox", "checkbox", "radio", "combobox", "listbox", "option",
    "menuitem", "menuitemcheckbox", "menuitemradio", "tab", "switch", "slider", "spinbutton", "menu",
    "menubar", "treeitem", "iframe", "img", "heading",
}
TRANSPARENT = {"generic", "none", "presentation", "InlineTextBox", "LineBreak", "LayoutTableCell",
               "LayoutTableRow", "LayoutTable", "Section", "Ignored"}
ROOT_ROLES = {"RootWebArea", "WebArea", "document"}
ROLE_ALIASES = {"image": "img", "Iframe": "iframe", "IframePresentational": "iframe", "StaticText": "text",
                "LabelText": "label", "Pre": "pre", "Abbr": "abbr", "Figcaption": "figcaption", "Legend": "legend",
                "DescriptionList": "list", "DescriptionListTerm": "term", "DescriptionListDetail": "definition"}
STATE_FLAGS = ("disabled", "expanded", "selected", "pressed", "required", "readonly", "multiselectable", "modal")


def is_ref(spec: str) -> bool:
    return bool(REF_RE.fullmatch(spec or ""))


def _val(d, key, default=None):
    v = d.get(key)
    if isinstance(v, dict):
        return v.get("value", default)
    return default if v is None else v


def _props(node: dict) -> dict:
    out = {}
    for p in node.get("properties") or []:
        out[p.get("name")] = _val(p, "value")
    return out


def _role(node: dict) -> str:
    r = _val(node, "role", "") or ""
    return ROLE_ALIASES.get(r, r)


def _name(node: dict) -> str:
    return (_val(node, "name", "") or "").strip()


def _attrs(role: str, props: dict) -> list[str]:
    out = []
    if role == "heading" and props.get("level") is not None:
        out.append(f"[level={props['level']}]")
    checked = props.get("checked")
    if checked in ("true", True):
        out.append("[checked]")
    elif checked == "mixed":
        out.append("[checked=mixed]")
    if props.get("focused") is True:
        out.append("[active]")
    for flag in STATE_FLAGS:
        v = props.get(flag)
        if v in (True, "true"):
            out.append(f"[{flag}]")
        elif v == "mixed":
            out.append(f"[{flag}=mixed]")
    return out


def build(nodes: list[dict], *, max_depth: int | None = None, root_backend_id: int | None = None,
          boxes: dict[int, tuple] | None = None) -> tuple[str, dict]:
    """Returns (outline text, refs). `boxes` maps backendDOMNodeId → (x, y, w, h) to append as [box=...]."""
    by_id = {n["nodeId"]: n for n in nodes}
    children_of = {n["nodeId"]: [c for c in n.get("childIds", []) if c in by_id] for n in nodes}
    refs: dict[str, dict] = {}
    lines: list[str] = []
    counter = [0]

    def real_children(nid: str) -> list[str]:
        """Children with ignored / transparent unnamed wrappers flattened away."""
        out: list[str] = []
        for cid in children_of.get(nid, []):
            c = by_id[cid]
            role = _role(c)
            if c.get("ignored") or (role in TRANSPARENT and not _name(c)) or role in ROOT_ROLES:
                out.extend(real_children(cid))
            else:
                out.append(cid)
        return out

    def emit(nid: str, depth: int, parent_name: str = "") -> None:
        node = by_id[nid]
        role = _role(node)
        name = _name(node)
        props = _props(node)
        indent = "  " * depth
        if role == "text":
            if name and name != parent_name:
                lines.append(f"{indent}- text: {name}")
            return
        kids = real_children(nid)
        parts = [f"- {role}"]
        if name:
            parts.append(f'"{name}"')
        parts.extend(_attrs(role, props))
        bid = node.get("backendDOMNodeId")
        if bid is not None and (role in INTERACTIVE or props.get("focusable") is True):
            counter[0] += 1
            ref = f"e{counter[0]}"
            refs[ref] = {"backend_node_id": bid, "role": role, "name": name}
            parts.append(f"[ref={ref}]")
            if boxes and bid in boxes:
                x, y, w, h = boxes[bid]
                parts.append(f"[box={x:g},{y:g},{w:g},{h:g}]")
        if role == "iframe":
            parts.append("[cross-origin content not included]")
            lines.append(indent + " ".join(parts))
            return
        value = _val(node, "value")
        text_kids = [k for k in kids if _role(by_id[k]) == "text"]
        other_kids = [k for k in kids if _role(by_id[k]) != "text"]
        if isinstance(value, str) and value != "" and role in INTERACTIVE:
            lines.append(indent + " ".join(parts) + f": {value}")
            return
        if kids and not other_kids and len(text_kids) == 1 and not name:
            lines.append(indent + " ".join(parts) + f": {_name(by_id[text_kids[0]])}")
            return
        visible_kids = [k for k in kids if not (_role(by_id[k]) == "text" and _name(by_id[k]) == name)]
        if visible_kids and (max_depth is None or depth + 1 < max_depth):
            lines.append(indent + " ".join(parts) + ":")
            for k in visible_kids:
                emit(k, depth + 1, name)
        elif visible_kids:
            lines.append(indent + " ".join(parts) + ": …")  # children hidden by --depth
        else:
            lines.append(indent + " ".join(parts))

    if root_backend_id is not None:
        roots = [n["nodeId"] for n in nodes if n.get("backendDOMNodeId") == root_backend_id]
        for r in roots:
            node = by_id[r]
            if node.get("ignored") or _role(node) in ROOT_ROLES or (_role(node) in TRANSPARENT and not _name(node)):
                for k in real_children(r):
                    emit(k, 0)
            else:
                emit(r, 0)
    else:
        tops = [n["nodeId"] for n in nodes if not n.get("parentId") or n.get("parentId") not in by_id]
        for top in tops:
            for k in real_children(top) if _role(by_id[top]) in ROOT_ROLES or by_id[top].get("ignored") else [top]:
                emit(k, 0)
    return "\n".join(lines), refs
