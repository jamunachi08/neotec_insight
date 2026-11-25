"""v3.9.11 — accounts in the order of ERPNext's chart-of-accounts tree.

ERPNext's tree lists each level's children by account name, so the tree order of
any set of accounts is: compare the names along the path from the root, level
by level. Used wherever a list of accounts is printed or exported (General
Ledger screen, print, PDF, Excel) so all of them follow the tree, whatever order
the accounts were picked in."""
from __future__ import annotations

import frappe


def name_key(name: str) -> str:
    """How one level is compared: case-insensitive, as the tree on screen."""
    return (name or "").casefold()


def tree_paths(parents: dict[str, str | None], names) -> dict[str, tuple]:
    """name -> (root name, …, own name) keys. Pure. Cycles and missing parents end
    the path where they occur."""
    out = {}
    for n in names:
        path, seen, cur = [], set(), n
        while cur and cur not in seen:
            seen.add(cur)
            path.append(name_key(cur))
            cur = parents.get(cur)
        out[n] = tuple(reversed(path))
    return out


def sort_by_tree(names: list[str], parents: dict[str, str | None]) -> list[str]:
    """`names` in chart-of-accounts tree order. Pure."""
    paths = tree_paths(parents, names)
    return sorted(names, key=lambda n: (paths[n], n))


def in_tree_order(names: list[str]) -> list[str]:
    """`names` (Account docnames) in tree order, reading their companies' charts."""
    names = list(dict.fromkeys(n for n in names if n))
    if len(names) < 2:
        return names
    companies = {r.company for r in frappe.get_all("Account", filters={"name": ["in", names]},
                                                  fields=["company"], distinct=True) if r.company}
    flt = {"company": ["in", sorted(companies)]} if companies else {"name": ["in", names]}
    parents = {r.name: r.parent_account for r in frappe.get_all(
        "Account", filters=flt, fields=["name", "parent_account"], limit_page_length=0)}
    return sort_by_tree(names, parents)
