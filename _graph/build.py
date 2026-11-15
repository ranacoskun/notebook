"""Read the Obsidian vault, check it, and write _graph/site/graph.json for the web viewer.

  python _graph/build.py            # build + show warnings
  python _graph/build.py --strict   # fail on errors (used by GitHub Actions)
"""
from __future__ import annotations
import json, re, sys
from collections import defaultdict
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent
VAULT = HERE.parent
FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")


def read(path):
    text = path.read_text(encoding="utf-8")
    m = FM_RE.match(text)
    if not m:
        return {}, text
    try:
        return (yaml.safe_load(m.group(1)) or {}), m.group(2)
    except yaml.YAMLError as e:
        raise ValueError(f"broken properties: {str(e).splitlines()[0]}")


def targets(value):
    """Property value -> list of link targets. Accepts "[[X]]", [[X]], plain X, or lists of them."""
    vals = value if isinstance(value, list) else [value]
    out = []
    for v in vals:
        if v is None:
            continue
        if isinstance(v, list):  # YAML parses unquoted [[X]] as a nested list
            v = "[[" + "".join(map(str, v[0] if v and isinstance(v[0], list) else v)) + "]]"
        v = str(v).strip()
        found = LINK_RE.findall(v)
        out += [f.strip() for f in found] if found else ([v] if v else [])
    return out


def section(body, heading):
    m = re.search(rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s|\Z)", body, re.S | re.M)
    return m.group(1) if m else ""


def short_label(t, meta, title):
    """Graph label: 'Malmberg 2017' for papers, otherwise the title."""
    if t != "paper":
        return title
    authors = meta.get("authors")
    if isinstance(authors, list):
        authors = ", ".join(str(a) for a in authors if a)
    authors = str(authors or "").strip()
    year = meta.get("year")
    year = str(year).strip() if year not in (None, "") else ""
    if authors:
        first = authors.split(",")[0].strip()
        last = first.split()[-1] if first else ""
        if last:
            return f"{last} {year}".strip()
    return title


def main():
    strict = "--strict" in sys.argv
    schema = yaml.safe_load((HERE / "schema.yaml").read_text(encoding="utf-8"))
    types, rels = schema["note_types"], schema["relations"]
    folder_type = {v["folder"].lower(): t for t, v in types.items()}
    errors, warnings = [], []

    notes = []
    for p in sorted(VAULT.rglob("*.md")):
        rel = p.relative_to(VAULT)
        if rel.parts[0].startswith((".", "_")) or rel.parts[0] == "Templates":
            continue
        try:
            meta, body = read(p)
        except ValueError as e:
            errors.append(f"{rel}: {e}")
            continue
        t = meta.get("type") or folder_type.get(rel.parts[0].lower())
        if t not in types:
            continue  # not a graph note (e.g. a daily note); ignore quietly
        notes.append((p.stem, t, meta, body, rel))

    index = {}
    for nid, t, meta, _, rel in notes:
        for name in [nid, meta.get("title"), *(meta.get("aliases") or [])]:
            if not name:
                continue
            key = str(name).lower()
            if key in index and index[key] != nid:
                errors.append(f"'{name}' is the name/alias of both '{index[key]}' and '{nid}' — merge them or fix aliases")
            index.setdefault(key, nid)

    nodes, edges, missing, ghosts = [], [], defaultdict(set), {}
    for nid, t, meta, body, rel in notes:
        for prop, value in meta.items():
            if prop not in rels:
                continue
            if t not in rels[prop]["from"]:
                errors.append(f"{rel}: a {t} note can't use '{prop}'")
                continue
            for name in targets(value):
                tid = index.get(name.lower())
                if tid:
                    edges.append({"source": nid, "target": tid, "rel": prop, "label": rels[prop]["label"]})
                else:
                    missing[name].add(nid)
                    ghost = "?" + name
                    edges.append({"source": nid, "target": ghost, "rel": prop, "label": rels[prop]["label"]})
                    ghosts.setdefault(ghost, {"id": ghost, "type": rels[prop]["to"][0], "title": name, "short_label": name,
                                              "aliases": [], "meta": {}, "props": {}, "rel_props": [], "folder": "",
                                              "n_defs": 0, "ghost": True,
                                              "body": "*No note yet. Create it in Obsidian by clicking the link.*"})
        n_defs = len(re.findall(r"^\s*[-*]\s+\S", section(body, "Definitions"), re.M))
        if t in schema.get("require_definition", []) and n_defs == 0:
            warnings.append(f"{rel}: no definitions yet")
        info = {k: meta[k] for k in ("citekey", "authors", "year", "venue", "doi", "paper_kind",
                                     "context", "sample", "design", "status") if meta.get(k) not in (None, "", [])}
        props = {k: v for k, v in meta.items() if k not in ("type", "title", "aliases") and v not in (None, "", [])}
        title = meta.get("title") or nid
        nodes.append({"id": nid, "type": t, "title": title, "short_label": short_label(t, meta, title),
                      "folder": rel.parts[0] if len(rel.parts) > 1 else "",
                      "props": props, "rel_props": [k for k in props if k in rels],
                      "aliases": [str(a) for a in (meta.get("aliases") or [])],
                      "meta": info, "n_defs": n_defs, "body": body})

    nodes += ghosts.values()  # links to notes that don't exist yet, shown faded like in Obsidian
    ids = {n["id"]: n["type"] for n in nodes if not n.get("ghost")}
    for e in edges:
        if e["target"] in ids and ids[e["target"]] not in rels[e["rel"]]["to"]:
            errors.append(f"{e['source']} → {e['rel']} → {e['target']}: '{e['rel']}' should point to a {' or '.join(rels[e['rel']]['to'])}")
    for name, srcs in sorted(missing.items()):
        warnings.append(f"[[{name}]] has no note yet (linked from {', '.join(sorted(srcs))})")

    out = HERE / "site" / "graph.json"
    out.write_text(json.dumps({"types": types, "nodes": nodes, "edges": edges}, ensure_ascii=False, default=str), encoding="utf-8")
    for w in warnings:
        print("warn :", w)
    for e in errors:
        print("ERROR:", e)
    print(f"{len(nodes) - len(ghosts)} notes, {len(edges)} links -> {out.relative_to(VAULT)}")
    if strict and errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
