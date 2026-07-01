# post_processing.py
# --------------------------------------------
# Dynamic parent/domain/category expansion for code annotations.
# Reads the full codebook CSV (P8_codes_full.csv) and automatically
# adds parent/domain/category annotations for any child concepts found.

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# -----------------------------
# Data structures
# -----------------------------

@dataclass(frozen=True)
class CodeNode:
    id: int
    parent_id: Optional[int]
    depth: Optional[int]
    type: Optional[str]
    name: str


class CodeHierarchy:
    """
    Builds dynamic mappings from the full code CSV:
      - id -> CodeNode
      - parent -> children
      - id -> ancestors (computed lazily/memoized)
    """

    def __init__(self, nodes: Dict[int, CodeNode]):
        self.nodes: Dict[int, CodeNode] = nodes
        self.children: Dict[int, Set[int]] = {}
        for node in nodes.values():
            if node.parent_id is not None:
                self.children.setdefault(node.parent_id, set()).add(node.id)
        self._ancestors_cache: Dict[int, List[int]] = {}

    def get_node(self, code_id: int) -> Optional[CodeNode]:
        return self.nodes.get(code_id)

    def ancestors(self, code_id: int) -> List[int]:
        """
        Returns ordered ancestors from immediate parent up to the root.
        e.g., [parent, grandparent, ...]
        """
        if code_id in self._ancestors_cache:
            return self._ancestors_cache[code_id]

        result: List[int] = []
        current = self.nodes.get(code_id)
        visited: Set[int] = set([code_id])

        while current and current.parent_id is not None:
            pid = current.parent_id
            if pid in visited:  # guard against any bad cycles
                break
            visited.add(pid)
            result.append(pid)
            current = self.nodes.get(pid)

        self._ancestors_cache[code_id] = result
        return result

    def is_valid(self, code_id: int) -> bool:
        return code_id in self.nodes


# -----------------------------
# Loader
# -----------------------------

def load_code_hierarchy(csv_path: str | Path) -> CodeHierarchy:
    """
    Load P8_codes_full.csv and build the CodeHierarchy.
    CSV is expected to have at least: Id, Parent Id, Depth, Type, Name
    """
    csv_path = Path(csv_path)
    if not csv_path.is_absolute():
        # Try to resolve relative to repo root
        repo_root = Path(__file__).parent.parent.resolve()
        candidate = repo_root / csv_path
        if candidate.exists():
            csv_path = candidate
    if not csv_path.exists():
        raise FileNotFoundError(f"Codebook CSV not found: {csv_path}")

    nodes: Dict[int, CodeNode] = {}

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        # Normalize headers (strip spaces)
        field_map = {k: k for k in reader.fieldnames or []}

        def pick(row: dict, key: str) -> Optional[str]:
            # robustly pick even if header spacing varies
            for col in row.keys():
                if col.strip().lower() == key.strip().lower():
                    return row[col]
            return None

        for row in reader:
            sid = pick(row, "Id")
            if not sid:
                continue
            try:
                cid = int(str(sid).strip())
            except ValueError:
                continue

            sparent = pick(row, "Parent Id")
            parent_id: Optional[int] = None
            if sparent and str(sparent).strip() != "":
                try:
                    parent_id = int(float(str(sparent).strip()))
                except (ValueError, TypeError):
                    parent_id = None

            sdepth = pick(row, "Depth")
            depth: Optional[int] = None
            if sdepth and str(sdepth).strip() != "":
                try:
                    depth = int(str(sdepth).strip())
                except ValueError:
                    depth = None

            ctype = pick(row, "Type")
            name = pick(row, "Name") or str(cid)

            node = CodeNode(
                id=cid,
                parent_id=parent_id,
                depth=depth,
                type=ctype.strip() if ctype else None,
                name=name.strip(),
            )
            nodes[cid] = node

    return CodeHierarchy(nodes)


# -----------------------------
# Core post-processing
# -----------------------------

def _norm_int(x) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


def _annotation_key(a: dict) -> Tuple:
    """
    Key to deduplicate identical annotations (same concept & quote span).
    """
    return (
        _norm_int(a.get("concept_id")),
        a.get("paragraph_id"),
        tuple(int(i) for i in (a.get("sentence_indices") or [])),
        a.get("age", "n/a"),
        # caused_by/rationale differences usually aren't part of "same annotation" identity
    )


def post_process_annotations(
    annotations: List[dict],
    code_hierarchy: CodeHierarchy,
    exclude_parents: Optional[Set[int]] = None,
    only_add_missing: bool = True,
    parent_rationale_template: str = (
        "Auto-added parent code '{parent_name}' because child concept "
        "{child_id} '{child_name}' was annotated for this quote."
    ),
) -> List[dict]:
    """
    Expand annotations by adding parent/domain/category codes for every child concept found.

    Parameters
    ----------
    annotations : list of dict
        Model-produced annotations.
    code_hierarchy : CodeHierarchy
        Loaded from the full codebook CSV.
    exclude_parents : set[int], optional
        If provided, parent IDs in this set are NOT auto-added.
        Use set() if you want *everything* added.
    only_add_missing : bool
        If True, don't add a parent if it's already present in the annotations for the same quote.
    parent_rationale_template : str
        Rationale text for auto-added parents.

    Returns
    -------
    List[dict]
        New list including original annotations and auto-added parent annotations.
    """
    exclude_parents = exclude_parents or set()

    # Build quick lookups for dedup checks
    out: List[dict] = []
    seen: Set[Tuple] = set()

    # Normalize originals and record them
    for a in annotations:
        # Ensure sentence_indices are ints and sorted (just to be consistent)
        sis = a.get("sentence_indices") or []
        a["sentence_indices"] = sorted(int(i) for i in sis)
        # Ensure concept_id is int
        a["concept_id"] = _norm_int(a.get("concept_id"))
        # Ensure age field
        if not a.get("age"):
            a["age"] = "n/a"
        k = _annotation_key(a)
        if k not in seen:
            seen.add(k)
            out.append(a)

    # Index child annotations by (paragraph_id, sentence_indices) so we can attach parents to the same quote
    quote_to_annotations: Dict[Tuple[str, Tuple[int, ...]], List[dict]] = {}
    for a in out:
        key = (a.get("paragraph_id"), tuple(a.get("sentence_indices") or []))
        quote_to_annotations.setdefault(key, []).append(a)

    # For each quote, compute which parents to add based on the child concepts present in that quote
    for key, anns in quote_to_annotations.items():
        # For dedup within quote
        present_in_quote: Set[int] = set(
            a["concept_id"] for a in anns if a.get("concept_id") is not None
        )

        # (parent_id, representative_child_annotation)
        to_add: List[Tuple[int, dict]] = []

        # Walk up ancestors for each present child concept
        for child_ann in anns:
            child_id = child_ann.get("concept_id")
            if child_id is None or not code_hierarchy.is_valid(child_id):
                continue

            for parent_id in code_hierarchy.ancestors(child_id):
                if parent_id in exclude_parents:
                    continue
                if only_add_missing and parent_id in present_in_quote:
                    continue
                # schedule this parent to add (use the first child that reaches it)
                to_add.append((parent_id, child_ann))

        # De-duplicate parent additions at the quote-level
        added_here: Set[int] = set()
        for parent_id, child_ann in to_add:
            if parent_id in added_here:
                continue
            added_here.add(parent_id)

            parent_node = code_hierarchy.get_node(parent_id)
            child_node = code_hierarchy.get_node(child_ann["concept_id"])
            if not parent_node or not child_node:
                continue

            parent_ann = {
                "paragraph_id": child_ann.get("paragraph_id"),
                "sentence_indices": list(child_ann.get("sentence_indices") or []),
                "concept_id": parent_node.id,
                "concept_name": parent_node.name,
                "age": child_ann.get("age") or "n/a",
                "caused_by": child_ann.get("caused_by") or [],
                "rationale": parent_rationale_template.format(
                    parent_name=parent_node.name,
                    child_id=child_node.id,
                    child_name=child_node.name,
                ),
            }

            k = _annotation_key(parent_ann)
            if k not in seen:
                seen.add(k)
                out.append(parent_ann)

    # Optional: stable sort (by paragraph, then first sentence index, then depth asc)
    def sort_key(a: dict) -> Tuple:
        pid = a.get("paragraph_id") or ""
        sis = a.get("sentence_indices") or []
        first_si = sis[0] if sis else -1
        node = code_hierarchy.get_node(a.get("concept_id") or -1)
        depth = node.depth if node and node.depth is not None else 999
        return (pid, first_si, depth, a.get("concept_id") or 0)

    out.sort(key=sort_key)
    return out


# -----------------------------
# Convenience helper for IDs only
# -----------------------------

def expand_code_ids_with_parents(
    code_ids: Set[int],
    code_hierarchy: CodeHierarchy,
    exclude_parents: Optional[Set[int]] = None,
) -> Set[int]:
    """
    For pure set-of-IDs workflows (e.g., your test harness), return the original
    ids plus all parent/domain/category ancestors.
    """
    exclude_parents = exclude_parents or set()
    result: Set[int] = set(code_ids)
    for cid in list(code_ids):
        if not code_hierarchy.is_valid(cid):
            continue
        for pid in code_hierarchy.ancestors(cid):
            if pid not in exclude_parents:
                result.add(pid)
    return result


# -----------------------------
# Example CLI usage (optional)
# -----------------------------

if __name__ == "__main__":
    """
    Optional CLI:
      python post_processing.py /path/to/P8_codes_full.csv /path/to/input_annotations.json /path/to/output_annotations.json

    Where input_annotations.json is a JSON array of annotations produced by your model.
    This will write a JSON array with parents added.
    """
    import json
    import sys

    if len(sys.argv) != 4:
        print(
            "Usage: python post_processing.py CODEBOOK_CSV INPUT_JSON OUTPUT_JSON",
            file=sys.stderr,
        )
        sys.exit(1)

    codebook_csv = sys.argv[1]
    input_json = sys.argv[2]
    output_json = sys.argv[3]

    hierarchy = load_code_hierarchy(codebook_csv)
    with open(input_json, "r", encoding="utf-8") as f:
        anns = json.load(f)

    processed = post_process_annotations(
        annotations=anns,
        code_hierarchy=hierarchy,
        exclude_parents=set(),  # Keep empty to include ALL parents (your preference)
        only_add_missing=True,
    )

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(processed)} annotations to {output_json}")
