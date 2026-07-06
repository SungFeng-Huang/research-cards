#!/usr/bin/env python3
"""Minimal JSON Canvas (.canvas) reader/writer for the Obsidian knowledge map.

The canvas is the Obsidian counterpart of the Heptabase knowledge-map
whiteboard: a human-curated spatial layout. Tooling is strictly ADDITIVE —
it appends missing file nodes in a staging grid below the existing content
and never moves or resizes nodes the user has arranged.
"""
import json, os, uuid


class Canvas:
    def __init__(self, path):
        self.path = path
        if os.path.exists(path):
            self.data = json.load(open(path))
        else:
            self.data = {}
        self.data.setdefault("nodes", [])
        self.data.setdefault("edges", [])
        self._staged = 0
        self._base_x = None
        self._base_y = None

    def file_paths(self):
        """Set of vault-relative .md paths that have a file node."""
        return {n.get("file") for n in self.data["nodes"]
                if n.get("type") == "file"}

    def add_file(self, relpath, width=400, height=360, color=None, per_row=5):
        """Append a file node in the staging grid; no-op if already present.
        Returns True if a node was added."""
        if relpath in self.file_paths():
            return False
        nodes = self.data["nodes"]
        if self._base_y is None:
            self._base_y = max((n.get("y", 0) + n.get("height", 0)
                                for n in nodes), default=0) + 120
            self._base_x = min((n.get("x", 0) for n in nodes), default=0)
        node = {"id": uuid.uuid4().hex[:16], "type": "file", "file": relpath,
                "x": self._base_x + (self._staged % per_row) * (width + 60),
                "y": self._base_y + (self._staged // per_row) * (height + 60),
                "width": width, "height": height}
        if color is not None:
            node["color"] = str(color)
        nodes.append(node)
        self._staged += 1
        return True

    def save(self):
        json.dump(self.data, open(self.path, "w"), ensure_ascii=False, indent=1)
