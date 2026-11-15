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
# Groups a decorator may name in `groups=`.
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
    group that isn't in DECLARED_GROUPS, so a typo fails at import, not silently."""
    unknown = sorted(set(groups) - set(DECLARED_GROUPS))
    if unknown:
        raise ValueError(
            f"unknown tool group(s) {', '.join(unknown)}; add to tool_groups.DECLARED_GROUPS"
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
    and `entries` is then `("default",)`."""

    entries: tuple[str, ...]
    configured: bool
    renamed: dict[str, Renamed]

    @classmethod
    def from_entries(cls, entries, renamed: dict[str, Renamed] | None = None) -> "Selection":
        entries = tuple(entries)
        renamed = RENAMED_TOOLS if renamed is None else renamed
        if not entries:
            return cls((DEFAULT,), False, renamed)
        return cls(entries, True, renamed)

    @property
    def selects_all(self) -> bool:
        return ALL in self.entries

    def _named_through_old_name(self, name: str) -> bool:
        return any(
            old in self.entries for old, target in self.renamed.items() if target.new == name
        )

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
            for old, target in self.renamed.items()
            if target.new == name and (self.selects_all or old in self.entries)
        )

    def old_names(self) -> list[str]:
        """The entries that are old names of a renamed tool."""
        return [entry for entry in self.entries if entry in self.renamed]

    def unknown_entries(self, tool_names) -> list[str]:
        """Entries that are neither a tool, a group nor an old name, in order."""
        known = set(tool_names) | GROUP_NAMES | set(self.renamed)
        return [entry for entry in self.entries if entry not in known]

    def group_entries(self) -> list[str]:
        return [entry for entry in self.entries if entry in GROUP_NAMES]

    def describe(self, tool_names) -> str:
        """The `instructions` line: what's loaded, and the setting for the rest."""
        tool_names = set(tool_names)
        total = len(tool_names)
        if self.selects_all:
            return f"Tools: every tool is loaded ({total}), because ENABLED_TOOLS includes all."
        groups = self.group_entries()
        named = sum(1 for e in self.entries if e in tool_names or e in self.renamed)
        parts = []
        if groups:
            parts.append(f"the {', '.join(groups)} tool group{'s' if len(groups) > 1 else ''}")
        if named:
            parts.append(f"{named} individually named tool{'s' if named > 1 else ''}")
        loaded = " plus ".join(parts) or "no tools"
        others = ", ".join(sorted(GROUP_NAMES - {ALL, DEFAULT}))
        return (
            f"Tools: this server loads {loaded}, out of {total}. To add more, set "
            f"ENABLED_TOOLS (or --include-tools) to tool names and groups ({others}), "
            "or all."
        )
