"""Build every teaching-prototype view from the loaded model.

``build_views`` returns view path (relative to ``views/``) -> HTML text.
Each record renders once on its owning page under a stable ``id`` anchor;
every other mention links to that anchor.
"""

from __future__ import annotations

from render_live import LIVE as LIVE
from render_live import commands_page, docs_pages
from render import (
    badge,
    code_field,
    esc,
    link,
    links_field,
    page,
    text_field,
    wrap,
)


class Pages:
    def __init__(self, model, live, coverage, docs, area_of):
        self.m, self.live, self.cov = model, live, coverage
        self.docs, self.area_of = docs, area_of

    # Locations -------------------------------------------------------------
    def concept(self, cid):
        return f"concepts/{self.m.concepts[cid]['page']}.html", cid, cid

    def surface(self, sid):
        return f"surfaces/{self.m.surfaces[sid]['page']}.html", None, sid

    def scenario(self, sid):
        return f"scenarios/{self.m.scenarios[sid]['page']}.html", None, sid

    def mapped(self, here, ids, indent):
        """Teaching rows counted per surface."""
        per_surface = {}
        for rid in ids:
            if rid in self.m.teaching:
                owner = self.m.teaching[rid]["owner"]
                per_surface[owner] = per_surface.get(owner, 0) + 1
        surfaces = [
            (page, None, f"{sid} ×{count}")
            for sid, count in per_surface.items()
            for page, _, _ in [self.surface(sid)]
        ]
        return links_field("Taught on", here, surfaces, indent)

    def refs(self, here, record, indent, skip=()):
        out = []
        for key, label, locate in (
            ("concepts", "Concepts", self.concept),
            ("topics", "Concepts", self.concept),
            ("surface_refs", "Surfaces", self.surface),
            ("surfaces", "Surfaces", self.surface),
            ("scenarios", "Scenarios", self.scenario),
            ("related_scenarios", "Related", self.scenario),
            ("boundaries", "Boundaries", lambda b: ("boundaries.html", b, b)),
            ("gaps", "Gaps", lambda g: (f"gaps/{g}.html", g, g)),
        ):
            if record.get(key) and key not in skip:
                out += links_field(
                    label, here, [locate(v) for v in record[key]], indent
                )
        return out

    def details(self, here, record, skip, indent="  "):
        out = []
        for key, value in record.items():
            if key in skip or key in _STRUCTURAL or not value:
                continue
            if key in ("sources", "commands", "functions", "skills", "recipes"):
                out += code_field(key.capitalize(), value, indent)
            elif key not in _REF_KEYS:
                out += text_field(key.replace("_", " ").capitalize(), value, indent)
        return out + self.refs(here, record, indent, skip)

    def heading(self, tag, anchor, record):
        return wrap(
            f'<{tag} id="{esc(anchor)}">{esc(record.get("title", anchor))}'
            f" {badge(record.get('status', ''))}</{tag}>"
        )

    # Concepts ---------------------------------------------------------------
    def concept_pages(self, views):
        body = []
        for entry in self.m.concept_files:
            if entry["parent"] is not None:
                continue
            for root in entry["roots"]:
                node = self.m.concepts[root]
                target, anchor, _ = self.concept(root)
                body.append(
                    f"<h2>{link('concepts.html', target, node['title'], anchor)}</h2>"
                )
                kids = [esc(self.m.concepts[k]["title"]) for k in node["children"]]
                body += wrap("<p>" + " · ".join(kids) + "</p>")
        views["concepts.html"] = page("concepts.html", "Concept tree", body)
        for entry in self.m.concept_files:
            here = f"concepts/{entry['stem']}.html"
            title = (
                self.m.concepts[entry["roots"][0]]["title"]
                if entry["roots"]
                else entry["stem"]
            )
            if entry["parent"]:
                title = f"{self.m.concepts[entry['parent']]['title']} (continued)"
            body = ["<ul>"]
            for root in entry["roots"]:
                body += self._concept_node(here, root, entry["stem"])
            views[here] = page(here, title, body + ["</ul>"])

    def _loc(self, cid):
        target, anchor, _ = self.concept(cid)
        return target, self.m.concepts[cid]["title"], anchor

    def _concept_node(self, here, cid, stem):
        node = self.m.concepts[cid]
        if node["page"] != stem:
            return [f"<li>{link(here, *self._loc(cid))} (own page)</li>"]
        gap = "" if self.cov[cid] else ' <span class="gap">unmapped</span>'
        out = wrap(
            f'<li id="{esc(cid)}"><b>{esc(node["title"])}</b> {badge(node["status"])}{gap}'
        )
        out += self.mapped(here, self.cov[cid], "  ")
        if node.get("related"):
            out += links_field("Related", here, [self.concept(node["related"])], "  ")
        out += self.details(here, node, {"title", "status", "related"})
        if node["children"]:
            out.append("<ul>")
            for child in node["children"]:
                out += self._concept_node(here, child, stem)
            out.append("</ul>")
        return out + ["</li>"]

    # Owned records: surfaces and scenarios -----------------------------------
    def owned_pages(self, views, kind, table, parts, title):
        index = []
        for oid, owner in sorted(table.items(), key=lambda kv: kv[1]["page"]):
            here = f"{kind}/{owner['page']}.html"
            index += wrap(
                f"<p>{link(f'{kind}.html', here, owner['title'], oid)} "
                f"{badge(owner['status'])}</p>"
            )
            body = self.heading("h2", oid, owner) + self.details(
                here, owner, {"title", "status"}
            )
            moved = {}
            for part_id in owner["parts"]:
                part = parts[part_id]
                if part["page"] != owner["page"]:
                    there = f"{kind}/{part['page']}.html"
                    moved.setdefault(there, []).append(part_id)
                    body += wrap(
                        f"<h3>{link(here, there, part['title'], part_id)}"
                        " (own page)</h3>"
                    )
                    continue
                body += self.heading("h3", part_id, part)
                body += self.details(here, part, {"title", "status"})
            views[here] = page(here, owner["title"], body)
            for there, part_ids in moved.items():
                body = wrap(f"<p>Continues {link(there, here, owner['title'], oid)}</p>")
                for part_id in part_ids:
                    body += self.heading("h3", part_id, parts[part_id])
                    body += self.details(there, parts[part_id], {"title", "status"})
                views[there] = page(there, f"{owner['title']} (continued)", body)
        views[f"{kind}.html"] = page(f"{kind}.html", title, index)

    # Evidence ---------------------------------------------------------------
    def evidence_pages(self, views):
        index = []
        for group in self.m.evidence_files:
            here = f"evidence/{group['stem']}.html"
            index += wrap(
                f"<p>{link('evidence.html', here, group['title'])} · "
                f"{len(group['records'])} records. {esc(group.get('scope', ''))}</p>"
            )
            body = wrap(f"<p>{esc(group.get('scope', ''))}</p>")
            for record in group["records"]:
                anchor = f"{group['stem']}/{record['id']}"
                body += self.heading("h2", anchor, record)
                body += self.details(here, record, {"title", "status", "id"}, "")
            views[here] = page(here, group["title"], body)
        views["evidence.html"] = page("evidence.html", "Evidence", index)

    # Record lists -----------------------------------------------
    def record_page(self, views, name, title, table):
        body = []
        for rid, record in table.items():
            if name == "gaps.html":
                here = f"gaps/{rid}.html"
                body += wrap(
                    f'<h2 id="{esc(rid)}">'
                    f"{link(name, here, record['title'], rid)} "
                    f"{badge(record['status'])}</h2>"
                )
                detail = self.heading("h2", rid, record) + self.details(
                    here, record, {"title", "status", "id"}, ""
                )
                views[here] = page(here, record["title"], detail)
            else:
                body += self.heading("h2", rid, record)
                body += self.details(name, record, {"title", "status", "id"}, "")
        views[name] = page(name, title, body)

    # Documentation graph, commands and overview ------------------------------
    def docs_pages(self, views):
        docs_pages(self, views)

    def commands_page(self, views):
        commands_page(self, views)


_STRUCTURAL = {
    "file",
    "page",
    "parts",
    "owner",
    "full_id",
    "parent",
    "children",
    "id",
    "position",
}
_REF_KEYS = {
    "concepts",
    "topics",
    "surface_refs",
    "surfaces",
    "scenarios",
    "related_scenarios",
    "boundaries",
    "gaps",
}
