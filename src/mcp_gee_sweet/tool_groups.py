"""Tool groups and deprecated aliases for ENABLED_TOOLS / --include-tools (#1364).

`ENABLED_TOOLS` is a comma-separated list of tool names and group names, and the
registered set is their union. Unset or empty means `default`. A tool's groups come
from its own decorator (`default=True`, `groups=(...)`, `local_only=True`) and its
module path, so a rename can't drift from a list kept here.

Pure: nothing here registers a tool or reads the environment, so `server.py` and the
tests share one resolution.
"""

from dataclasses import dataclass

ALL = "all"
DEFAULT = "default"
LOCAL_FILES = "local-files"
# Derived from the tool's module: mcp_gee_sweet.tools.<service>[.<module>].
SERVICE_GROUPS = ("sheets", "drive", "docs", "calendar", "gmail", "cache")
# Groups only a decorator puts a tool in. `groups=` also takes a service group, for
# a tool that belongs to a second service as well as its own module's (#1511: the
# spreadsheet tools under tools/drive/ are in `sheets` too).
DECLARED_GROUPS = ("comments",)
GROUP_NAMES = frozenset({ALL, DEFAULT, LOCAL_FILES, *SERVICE_GROUPS, *DECLARED_GROUPS})

_TOOLS_PACKAGE = "mcp_gee_sweet.tools."


@dataclass(frozen=True)
class Renamed:
    """An old tool name kept as a deprecated alias of `new` until `removed_in`."""

    new: str
    removed_in: str


# Old name -> its replacement (#1209). An old name in ENABLED_TOOLS registers the new
# tool, with a startup warning, plus a callable alias under the old name; `all`
# registers every alias too. Groups never carry an alias.
# Policy: docs/design.md, "Renaming or Removing a Tool". Remove an entry one feature
# release after it's added.
RENAMED_TOOLS: dict[str, Renamed] = {}


def service_group(module: str) -> str | None:
    """The service group a tool defined in `module` belongs to, if any."""
    if not module.startswith(_TOOLS_PACKAGE):
        return None
    service = module[len(_TOOLS_PACKAGE) :].split(".", 1)[0]
    return service if service in SERVICE_GROUPS else None


def tool_groups(
    module: str, *, default: bool = False, local_only: bool = False, groups=()
) -> frozenset[str]:
    """Every group a tool belongs to, `all` aside. Raises ValueError for a declared
    group that's neither in DECLARED_GROUPS nor a service group, so a typo fails at
    import, not silently."""
    unknown = sorted(set(groups) - set(DECLARED_GROUPS) - set(SERVICE_GROUPS))
    if unknown:
        raise ValueError(
            f"unknown tool group(s) {', '.join(unknown)} in groups=: it takes a service "
            f"group ({', '.join(SERVICE_GROUPS)}) or a declared one "
            f"({', '.join(DECLARED_GROUPS)}). Use default=True for `{DEFAULT}` and "
            f"local_only=True for `{LOCAL_FILES}`; a new group goes in "
            "tool_groups.DECLARED_GROUPS."
        )
    result = set(groups)
    if default:
        result.add(DEFAULT)
    if local_only:
        result.add(LOCAL_FILES)
    if service := service_group(module):
        result.add(service)
    return frozenset(result)


def parse_entries(text: str | None) -> tuple[str, ...]:
    """The entries of an ENABLED_TOOLS value in order, stripped, blanks and repeats
    dropped. Case-sensitive: `ALL` is an unknown entry, not `all`."""
    seen: dict[str, None] = {}
    for entry in (text or "").split(","):
        if entry := entry.strip():
            seen.setdefault(entry, None)
    return tuple(seen)


@dataclass(frozen=True)
class Selection:
    """What ENABLED_TOOLS selects. `configured` is False when it's unset or empty,
    and `entries` is then `("default",)`. Holds its own copy of the rename map, as
    a tuple, so it stays immutable and hashable."""

    entries: tuple[str, ...]
    configured: bool
    renamed_items: tuple[tuple[str, Renamed], ...]

    @classmethod
    def from_entries(cls, entries, renamed: dict[str, Renamed] | None = None) -> "Selection":
        entries = tuple(entries)
        items = tuple(sorted((RENAMED_TOOLS if renamed is None else renamed).items()))
        if not entries:
            return cls((DEFAULT,), False, items)
        return cls(entries, True, items)

    @property
    def renamed(self) -> dict[str, Renamed]:
        return dict(self.renamed_items)

    @property
    def selects_all(self) -> bool:
        return ALL in self.entries

    def _named_through_old_name(self, name: str) -> bool:
        return any(old in self.entries for old, target in self.renamed_items if target.new == name)

    def names(self, name: str) -> bool:
        """Whether `name` is listed by itself, or through an old name of it."""
        return name in self.entries or self._named_through_old_name(name)

    def selects(self, name: str, groups: frozenset[str]) -> bool:
        return self.selects_all or self.names(name) or bool(groups.intersection(self.entries))

    def aliases_for(self, name: str) -> list[str]:
        """The old names of `name` to register as callable aliases: those listed by
        themselves, or every one under `all`."""
        return sorted(
            old
            for old, target in self.renamed_items
            if target.new == name and (self.selects_all or old in self.entries)
        )

    def old_names(self) -> list[str]:
        """The entries that are old names of a renamed tool."""
        renamed = self.renamed
        return [entry for entry in self.entries if entry in renamed]

    def unknown_entries(self, tool_names) -> list[str]:
        """Entries that are neither a tool, a group nor an old name, in order."""
        known = set(tool_names) | GROUP_NAMES | set(self.renamed)
        return [entry for entry in self.entries if entry not in known]

    def group_entries(self) -> list[str]:
        return [entry for entry in self.entries if entry in GROUP_NAMES]

    def describe(self, registered: dict[str, frozenset[str]], total: int, aliases: int = 0) -> str:
        """The `instructions` line, built from what actually registered: `registered`
        maps each registered tool (aliases aside) to its groups, out of `total` tools.

        A listed group is named only if it registered a tool, and a listed tool is
        counted only if no listed group already brought it in, so the line never
        claims a tool the client can't call (PR #1501 QA round 1)."""
        count = len(registered)
        alias_note = (
            f", plus {aliases} deprecated alias{'es' if aliases > 1 else ''}" if aliases else ""
        )
        if self.selects_all:
            if count == total:
                return (
                    f"Tools: every tool is loaded ({total}{alias_note}), because "
                    "ENABLED_TOOLS includes all."
                )
            return (
                f"Tools: this server loads {count} of {total} tools{alias_note}. "
                "ENABLED_TOOLS includes all, and the local-file policy "
                "(LOCAL_FILE_ACCESS) leaves out the rest."
            )
        listed_groups = set(self.group_entries())
        groups = [
            g
            for g in self.group_entries()
            if any(g in member_of for member_of in registered.values())
        ]
        named = sum(
            1
            for name, member_of in registered.items()
            if self.names(name) and not member_of.intersection(listed_groups)
        )
        parts = []
        if groups:
            parts.append(f"the {', '.join(groups)} tool group{'s' if len(groups) > 1 else ''}")
        if named:
            parts.append(f"{named} individually named tool{'s' if named > 1 else ''}")
        what = f" ({' plus '.join(parts)})" if parts else ""
        others = ", ".join(sorted(GROUP_NAMES - {ALL, DEFAULT}))
        return (
            f"Tools: this server loads {count} of {total} tools{what}{alias_note}. "
            "To add more, set ENABLED_TOOLS (or --include-tools) to tool names and "
            f"groups ({others}), or all."
        )
