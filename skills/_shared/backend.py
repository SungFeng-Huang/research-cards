#!/usr/bin/env python3
"""Backend abstraction for research-cards skills.

Skills author in MARKDOWN (the lingua franca); the backend maps it to the
native store:

  HeptabaseBackend  - `heptabase` CLI; markdown -> ProseMirror via md2pm for
                      full-body saves, native markdown for create/append.
  ObsidianBackend   - plain .md files with YAML frontmatter in a vault.

Card references inside markdown use Obsidian syntax everywhere:
  [[Card Title]] / [[Card Title|label]]  - link to a card in a collection
Each backend resolves them natively (Obsidian: as-is; Heptabase: converted
to app.heptabase.com card links by md2pm).

Usage:
    from backend import get_backend
    be = get_backend()               # reads ~/.config/research-cards/config.json
    cid = be.create_card("papers", "Title", md_body, {"Status": "TODO"})
"""
import datetime, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import hbconfig
import md2pm
from pmmd import Converter, assemble, safe_filename


def _cli(*args, timeout=120):
    r = subprocess.run(["heptabase", *args], capture_output=True, text=True,
                       timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"heptabase {' '.join(args[:3])}: {r.stderr[:300]}")
    return json.loads(r.stdout)


def fm_key(prop_name):
    return re.sub(r"[ /]+", "_", prop_name.strip().lower())


# --------------------------------------------------------------------- base
class Card:
    def __init__(self, id, title, md, props, collection=None):
        self.id, self.title, self.md = id, title, md
        self.props = props or {}
        self.collection = collection


class Backend:
    """Operation set every backend implements. All bodies are markdown."""
    name = "?"

    def list_cards(self, collection):              # -> [{id, title, props, modified}]
        raise NotImplementedError

    def read_card(self, card_id):                  # -> Card
        raise NotImplementedError

    def create_card(self, collection, title, md, props=None):  # -> card id
        raise NotImplementedError

    def save_card(self, card_id, md):              # replace body
        raise NotImplementedError

    def append_card(self, card_id, md):
        raise NotImplementedError

    def set_props(self, card_id, props):           # {prop name: value}
        raise NotImplementedError

    def card_link(self, title, label=None):        # inline reference markdown
        return f"[[{title}|{label}]]" if label and label != title else f"[[{title}]]"


# ---------------------------------------------------------------- obsidian
class ObsidianBackend(Backend):
    name = "obsidian"

    def __init__(self, cfg):
        self.cfg = cfg
        self.vault = cfg["obsidian"]["vault"]
        self.folders = cfg["obsidian"].get("folders") or {}
        if not os.path.isdir(self.vault):
            raise hbconfig.ConfigError(f"Obsidian vault 不存在：{self.vault}")

    # --- id scheme: "<folder>/<filename>" (no .md), stable & human-readable
    def _path(self, card_id):
        # card ids come from filenames/config/state, but guard anyway:
        # never resolve outside the vault
        p = os.path.join(self.vault, card_id + ".md")
        if os.path.isabs(card_id) or ".." in card_id.split("/") \
                or not os.path.realpath(p).startswith(
                    os.path.realpath(self.vault) + os.sep):
            raise ValueError(f"card id 逸出 vault：{card_id!r}")
        return p

    def _folder(self, collection):
        folder = self.folders.get(collection, collection)
        os.makedirs(os.path.join(self.vault, folder), exist_ok=True)
        return folder

    @staticmethod
    def _parse(path):
        import yaml
        text = open(path).read()
        m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
        if not m:
            return {}, text
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            fm = {}
        return fm, text[m.end():].lstrip("\n")

    @staticmethod
    def _dump_fm(fm):
        lines = ["---"]
        for k, v in fm.items():
            if isinstance(v, list):
                lines.append(f"{k}:")
                lines += [f"  - {json.dumps(x, ensure_ascii=False)}" for x in v]
            else:
                lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
        lines.append("---")
        return "\n".join(lines)

    def list_cards(self, collection):
        folder = self._folder(collection)
        out = []
        fdir = os.path.join(self.vault, folder)
        for fn in sorted(os.listdir(fdir)):
            if not fn.endswith(".md"):
                continue
            fm, _ = self._parse(os.path.join(fdir, fn))
            out.append({"id": f"{folder}/{fn[:-3]}",
                        "title": fm.get("title") or fn[:-3],
                        "props": {k: v for k, v in fm.items()},
                        "modified": datetime.datetime.fromtimestamp(
                            os.path.getmtime(os.path.join(fdir, fn))).isoformat()})
        return out

    def read_card(self, card_id):
        fm, body = self._parse(self._path(card_id))
        return Card(card_id, fm.get("title") or os.path.basename(card_id),
                    body, fm, card_id.split("/")[0])

    def create_card(self, collection, title, md, props=None):
        folder = self._folder(collection)
        base = safe_filename(title)
        name, i = base, 1
        while os.path.exists(os.path.join(self.vault, folder, name + ".md")):
            i += 1
            name = f"{base} ({i})"
        fm = {"title": title}
        for k, v in (props or {}).items():
            fm[fm_key(k)] = v
        fm["created"] = datetime.datetime.now().astimezone().isoformat()
        with open(os.path.join(self.vault, folder, name + ".md"), "w") as f:
            f.write(self._dump_fm(fm) + "\n\n" + md.strip() + "\n")
        return f"{folder}/{name}"

    def save_card(self, card_id, md):
        path = self._path(card_id)
        fm, _ = self._parse(path)
        with open(path, "w") as f:
            f.write(self._dump_fm(fm) + "\n\n" + md.strip() + "\n")

    def append_card(self, card_id, md):
        with open(self._path(card_id), "a") as f:
            f.write("\n" + md.strip() + "\n")

    def set_props(self, card_id, props):
        path = self._path(card_id)
        fm, body = self._parse(path)
        for k, v in props.items():
            fm[fm_key(k)] = v
        with open(path, "w") as f:
            f.write(self._dump_fm(fm) + "\n\n" + body)

    # ---- doc-level API: PM doc as the shared in-memory model --------------
    # Skills that manipulate ProseMirror docs (insert sections, colorize,
    # place figures) work unchanged on Obsidian: markdown <-> PM via the
    # plugin dialect. Wikilinks stay literal text; ![[file]] round-trips.

    def _md2pm_ctx(self):
        return {"mode": "obsidian", "self_id": "", "workspace": "",
                "name_to_card": {}, "attach_to_fileid": {},
                "anchor_short_to_full": {}}

    def _name_to_id(self):
        """filename (no .md) -> obsidian card id, across all collections."""
        out = {}
        for collection in self.folders:
            folder = self.folders[collection]
            fdir = os.path.join(self.vault, folder)
            if not os.path.isdir(fdir):
                continue
            for fn in os.listdir(fdir):
                if fn.endswith(".md"):
                    out[fn[:-3]] = f"{folder}/{fn[:-3]}"
        return out

    def _md_to_doc(self, md, resolve_wikilinks=False):
        nodes = md2pm.BlockParser(self._md2pm_ctx()).parse(md)
        doc = {"type": "doc", "content": nodes}
        if resolve_wikilinks:
            name_to_id = self._name_to_id()

            def walk(n):
                content = n.get("content")
                if not content:
                    return
                out = []
                for ch in content:
                    if ch.get("type") == "text" and not ch.get("marks"):
                        out.extend(self._split_wikilinks(ch, name_to_id))
                    else:
                        walk(ch)
                        out.append(ch)
                n["content"] = out
            walk(doc)
        return doc

    @staticmethod
    def _split_wikilinks(text_node, name_to_id):
        """Plain [[Name]] in a bare text node -> card mention node."""
        text = text_node.get("text", "")
        parts, pos = [], 0
        for m in re.finditer(r"\[\[([^\]|#^]+?)\]\]", text):
            cid = name_to_id.get(m.group(1).strip())
            if not cid:
                continue
            if m.start() > pos:
                parts.append({"type": "text", "text": text[pos:m.start()]})
            parts.append({"type": "card", "attrs": {"cardId": cid}})
            pos = m.end()
        if not parts:
            return [text_node]
        if pos < len(text):
            parts.append({"type": "text", "text": text[pos:]})
        return parts

    @staticmethod
    def _plain_text(n):
        if n.get("type") == "text":
            return n.get("text", "")
        return "".join(ObsidianBackend._plain_text(c)
                       for c in n.get("content") or [])

    def _doc_to_md(self, doc, title=""):
        # drop the leading H1 title (it lives in frontmatter) — compare PLAIN
        # text so marks added by colorize etc. don't defeat the match
        content = list(doc.get("content") or [])
        if content and content[0].get("type") == "heading" \
                and (content[0].get("attrs") or {}).get("level") == 1 \
                and self._plain_text(content[0]).strip() == (title or "").strip():
            content = content[1:]
        doc = {"type": "doc", "content": content}
        conv = Converter({"id": "", "title": title})
        _, blocks = conv.convert_blocks(doc)
        md = assemble(m for _, m in blocks)
        # resolve card mentions (skills may insert {"type":"card"} nodes whose
        # cardId is an obsidian id "Folder/Name") -> wikilink
        return re.sub(r"%%HEPTA-CARD:([^%]+)%%",
                      lambda m: f"[[{m.group(1).split('/')[-1]}]]", md)

    @staticmethod
    def _hash(text):
        import hashlib
        return hashlib.sha1(text.encode()).hexdigest()

    def read_doc(self, card_id):
        fm, body = self._parse(self._path(card_id))
        doc = self._md_to_doc(body, resolve_wikilinks=True)
        # mirror Heptabase doc shape: body starts with an H1 title node
        # (skills position inserts relative to it); save_doc strips it back.
        title = fm.get("title") or os.path.basename(card_id)
        doc["content"].insert(0, {
            "type": "heading", "attrs": {"id": None, "level": 1},
            "content": [{"type": "text", "text": title}]})
        return self._hash(body), doc

    def save_doc(self, card_id, ver, doc):
        path = self._path(card_id)
        fm, body = self._parse(path)
        if ver is not None and self._hash(body) != ver:
            raise RuntimeError(f"{card_id}: 檔案在讀取後被修改（hash 不符）")
        md = self._doc_to_md(doc, fm.get("title") or "")
        with open(path, "w") as f:
            f.write(self._dump_fm(fm) + "\n\n" + md)

    def create_doc(self, collection, markdown):
        """Create from markdown whose first line may be '# Title'."""
        lines = markdown.strip().split("\n")
        title = lines[0][2:].strip() if lines and lines[0].startswith("# ") else "untitled"
        body = "\n".join(lines[1:]).strip() if lines[0].startswith("# ") else markdown
        return self.create_card(collection, title, body)

    def read_content_str(self, card_id):
        _, body = self._parse(self._path(card_id))
        return body

    def search_cards(self, query, limit=5):
        out = []
        q = query.lower()
        for collection in self.folders:
            for c in self.list_cards(collection):
                if q in c["title"].lower() or q in c["id"].lower():
                    out.append(c)
                elif q in self.read_content_str(c["id"]).lower():
                    out.append(c)
                if len(out) >= limit:
                    return out
        return out

    # ---- journal: daily note <date>.md — folder from obsidian.journal.folder
    # (empty string = vault root, backward compatible) ----------------------
    def _journal_path(self, date_str):
        jdir = hbconfig.journal_dir(self.cfg)
        os.makedirs(jdir, exist_ok=True)
        return os.path.join(jdir, date_str + ".md")

    def journal_append(self, date_str, markdown):
        with open(self._journal_path(date_str), "a") as f:
            f.write("\n" + markdown.strip() + "\n")

    def journal_read_doc(self, date_str):
        p = self._journal_path(date_str)
        body = open(p).read() if os.path.exists(p) else ""
        return self._hash(body), self._md_to_doc(body)

    def journal_save_doc(self, date_str, ver, doc):
        p = self._journal_path(date_str)
        body = open(p).read() if os.path.exists(p) else ""
        if ver is not None and self._hash(body) != ver:
            raise RuntimeError(f"journal {date_str}: 檔案在讀取後被修改")
        with open(p, "w") as f:
            f.write(self._doc_to_md(doc))


# --------------------------------------------------------------- heptabase
class HeptabaseBackend(Backend):
    name = "heptabase"

    def __init__(self, cfg):
        self.cfg = cfg
        self.workspace = cfg["heptabase"]["workspace_id"]
        self.collections = cfg["heptabase"]["collections"]
        self._title_index = None   # title -> card id (lazy, for [[wikilink]])

    # --- collection helpers
    def _col(self, collection):
        if collection not in self.collections:
            raise KeyError(f"未知 collection: {collection}")
        return self.collections[collection]

    def _tag_props(self, tag_id):
        return {p["name"]: p for p in _cli("tag", "properties", tag_id)["properties"]}

    def _title_map(self):
        if self._title_index is None:
            self._title_index = {}
            for col in self.collections.values():
                for c in _cli("tag", "cards", col["tag_id"])["cards"]:
                    self._title_index[c["title"]] = c["id"]
                    # allow linking by safe filename too (Obsidian habit)
                    self._title_index.setdefault(safe_filename(c["title"]), c["id"])
        return self._title_index

    # --- markdown [[wikilinks]] -> heptabase card links
    def _resolve_links(self, md):
        def repl(m):
            target, label = m.group(1), m.group(2)
            cid = self._title_map().get(target)
            if not cid:
                raise ValueError(f"[[{target}]] 不是已知卡片標題，無法轉成 Heptabase 連結")
            url = f"https://app.heptabase.com/{self.workspace}/card/{cid}"
            return f"[{label or target}]({url})"
        return re.sub(r"(?<!\!)\[\[([^\]|#^]+?)(?:\|([^\]]*))?\]\]", repl, md)

    def list_cards(self, collection):
        col = self._col(collection)
        cards = _cli("tag", "cards", col["tag_id"], "--include-properties")["cards"]
        flt = col.get("filter")
        if flt:
            (pn, pv), = flt.items()
            cards = [c for c in cards
                     if any(p["name"] == pn and p.get("value") == pv
                            for p in c.get("properties") or [])]
        return [{"id": c["id"], "title": c["title"],
                 "props": {p["name"]: p.get("value")
                           for p in c.get("properties") or []},
                 "modified": c.get("lastEditedTime")} for c in cards]

    def read_card(self, card_id):
        note = _cli("note", "read", card_id)
        conv = Converter({"id": card_id, "title": note.get("title") or ""})
        body = conv.convert(json.loads(note["content"]))
        props = {}
        try:
            for tag in _cli("card", "properties", card_id).get("tags") or []:
                for p in tag.get("properties") or []:
                    props[p["name"]] = p.get("value")
        except RuntimeError:
            pass
        return Card(card_id, note.get("title") or "", body, props)

    def create_card(self, collection, title, md, props=None):
        col = self._col(collection)
        content = f"# {title}\n\n{self._resolve_links(md).strip()}\n"
        created = _cli("note", "create", "--content", content)
        cid = created["id"]
        _cli("tag", "add", "--card-id", cid, "--tag-name", col["tag_name"])
        merged = dict(col.get("new_card_props") or {})
        merged.update(props or {})
        if merged:
            self.set_props(cid, merged)
        return cid

    def append_card(self, card_id, md):
        _cli("note", "append", card_id, "--content", self._resolve_links(md))

    def save_card(self, card_id, md):
        """Full-body replace: markdown -> ProseMirror. Colors/toggles in the
        OLD body are lost; prefer block-level edits (append) or the
        obsidian-sync write-back for surgical changes."""
        note = _cli("note", "read", card_id)
        parser = md2pm.BlockParser({
            "self_id": card_id, "workspace": self.workspace,
            "name_to_card": {t: i for t, i in self._title_map().items()},
            "attach_to_fileid": {}, "anchor_short_to_full": {}})
        nodes = parser.parse(self._resolve_links(md))
        doc = json.dumps({"type": "doc", "content": nodes}, ensure_ascii=False)
        _cli("note", "save", card_id, "--content-md5", note["contentMd5"],
             "--content", doc)

    def set_props(self, card_id, props):
        # find property ids across this card's tag databases
        info = _cli("card", "properties", card_id)
        by_name = {}
        for tag in info.get("tags") or []:
            for p in tag.get("properties") or []:
                by_name.setdefault(p["name"], p)
        for name, value in props.items():
            pdef = by_name.get(name)
            if pdef is None:
                raise KeyError(f"卡片 {card_id} 沒有屬性 {name!r}")
            if isinstance(value, (list, dict, bool)) or value is None:
                _cli("card", "set-property", card_id, "--property-id", pdef["id"],
                     "--json-value", json.dumps(value, ensure_ascii=False))
            else:
                _cli("card", "set-property", card_id, "--property-id", pdef["id"],
                     "--value", str(value))


def get_backend(cfg=None):
    cfg = cfg or hbconfig.load_config()
    # "both": Heptabase is canonical for authoring; obsidian-sync mirrors.
    if cfg["backend"] in ("heptabase", "both"):
        return HeptabaseBackend(cfg)
    return ObsidianBackend(cfg)


def obsidian_or_none():
    """Routing guard for skills: an ObsidianBackend when config says
    backend='obsidian', else None (legacy heptabase paths run untouched)."""
    try:
        cfg = hbconfig.load_config()
        return ObsidianBackend(cfg) if cfg["backend"] == "obsidian" else None
    except Exception:
        return None
