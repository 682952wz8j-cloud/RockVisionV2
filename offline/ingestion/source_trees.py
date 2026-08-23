"""Read-only extra incoming trees that sit beside a unique wall_* folder.

New captures are sometimes dropped at incoming/<capture>/ instead of
incoming/wall_<id>/<capture>/. Those files stay where they are; this module
only lists them so ingest/qualify can read them.
"""

from __future__ import annotations

from pathlib import Path

from .hashing import snapshot_hashes
from .scan import iter_files


def discover_source_trees(root: Path, wall_id: str) -> list[dict]:
    incoming_parent = root / "incoming"
    wall = incoming_parent / wall_id
    trees = [
        {
            "id": "wall",
            "path": wall,
            "relativePrefix": "",
            "role": "wallIncoming",
            "name": wall_id,
        }
    ]
    if not incoming_parent.is_dir():
        return trees
    wall_dirs = sorted(
        path for path in incoming_parent.iterdir() if path.is_dir() and path.name.startswith("wall_")
    )
    extras = sorted(
        path
        for path in incoming_parent.iterdir()
        if path.is_dir() and not path.name.startswith("wall_") and not path.name.startswith(".")
    )
    if len(wall_dirs) != 1 or wall_dirs[0].name != wall_id:
        return trees
    for extra in extras:
        trees.append(
            {
                "id": f"incoming_sibling:{extra.name}",
                "path": extra,
                "relativePrefix": f"../{extra.name}",
                "role": "incomingSibling",
                "name": extra.name,
            }
        )
    return trees


def trees_from_inventory(incoming_wall: Path, inventory: dict | None) -> list[dict]:
    listed = (inventory or {}).get("sourceTrees") or []
    if not listed:
        return [
            {
                "id": "wall",
                "path": incoming_wall,
                "relativePrefix": "",
                "role": "wallIncoming",
                "name": incoming_wall.name,
            }
        ]
    trees = []
    parent = incoming_wall.parent
    for item in listed:
        prefix = item.get("relativePrefix") or ""
        if item.get("id") == "wall" or not prefix:
            trees.append(
                {
                    "id": item.get("id") or "wall",
                    "path": incoming_wall,
                    "relativePrefix": "",
                    "role": item.get("role") or "wallIncoming",
                    "name": item.get("name") or incoming_wall.name,
                }
            )
            continue
        name = Path(prefix).name
        trees.append(
            {
                "id": item.get("id") or f"incoming_sibling:{name}",
                "path": parent / name,
                "relativePrefix": prefix,
                "role": item.get("role") or "incomingSibling",
                "name": item.get("name") or name,
            }
        )
    return trees


def inventory_relative_path(tree: dict, path: Path) -> str:
    inner = path.relative_to(tree["path"]).as_posix()
    prefix = tree.get("relativePrefix") or ""
    if not prefix:
        return inner
    return f"{prefix}/{inner}"


def iter_tree_files(trees: list[dict]) -> list[tuple[dict, Path, str]]:
    collected: list[tuple[dict, Path, str]] = []
    for tree in trees:
        root = tree["path"]
        if not root.is_dir():
            continue
        for path in iter_files(root):
            collected.append((tree, path, inventory_relative_path(tree, path)))
    collected.sort(key=lambda item: item[2])
    return collected


def snapshot_source_trees(trees: list[dict]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for tree in trees:
        root = tree["path"]
        if not root.is_dir():
            continue
        prefix = tree.get("relativePrefix") or ""
        for rel, digest in snapshot_hashes(root).items():
            key = f"{prefix}/{rel}" if prefix else rel
            hashes[key] = digest
    return hashes


def resolve_incoming_path(incoming_wall: Path, relative_path: str) -> Path:
    return incoming_wall / relative_path


def source_tree_public(tree: dict) -> dict:
    return {
        "id": tree["id"],
        "name": tree.get("name"),
        "role": tree.get("role"),
        "relativePrefix": tree.get("relativePrefix") or "",
        "path": str(tree["path"]),
    }
