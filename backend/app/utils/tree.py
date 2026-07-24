"""Generic tree-building utilities."""

from typing import TypeVar, Callable, Optional, Sequence

T = TypeVar("T")


def build_tree(
    items: Sequence[T],
    *,
    id_getter: Callable[[T], str],
    parent_getter: Callable[[T], Optional[str]],
    sort_key: Optional[Callable[[T], int]] = None,
) -> list[dict]:
    """Build a nested tree from a flat list of items.

    Args:
        items: Flat list of items (e.g., ORM models or dicts).
        id_getter: Function to extract the unique ID of an item.
        parent_getter: Function to extract the parent ID; returns None for roots.
        sort_key: Optional function to sort siblings.

    Returns:
        List of root nodes, each with a "children" list.
    """
    item_map: dict[str, dict] = {}
    for item in items:
        item_id = id_getter(item)
        item_map[item_id] = {
            "item": item,
            "children": [],
        }

    roots: list[dict] = []
    for item in items:
        item_id = id_getter(item)
        parent_id = parent_getter(item)
        node = item_map[item_id]
        if parent_id and parent_id in item_map:
            item_map[parent_id]["children"].append(node)
        else:
            roots.append(node)

    if sort_key is not None:

        def _sort(nodes: list[dict]) -> None:
            nodes.sort(key=lambda n: sort_key(n["item"]))
            for child in nodes:
                _sort(child["children"])

        _sort(roots)

    return roots


def tree_to_dict(
    tree_nodes: list[dict],
    converter: Callable[[T], dict],
) -> list[dict]:
    """Convert tree nodes built by `build_tree` into plain dicts.

    Args:
        tree_nodes: Output from `build_tree`.
        converter: Function to convert the original item into a dict.

    Returns:
        Nested list of dicts with a "children" key.
    """
    result: list[dict] = []
    for node in tree_nodes:
        item_dict = converter(node["item"])
        item_dict["children"] = tree_to_dict(node["children"], converter)
        result.append(item_dict)
    return result
