"""Deprecating a tool or a tool parameter for one release before removal (#1209).

The policy is in docs/design.md, "Renaming or Removing a Tool". A renamed tool's old
name is `tool_groups.RENAMED_TOOLS`'s job; this module covers the other two cases:

- `deprecated_tool`: a tool that will be removed. Its description opens with a note
  naming what to use instead, and the server warns at startup when ENABLED_TOOLS
  names it.
- `renamed_params`: a parameter that was renamed. The old name is still accepted for
  one release, and the result carries a warning under `DEPRECATION_WARNINGS_KEY`.
- `with_deprecation_warnings`: the same warning, for a removed parameter the tool
  still accepts for one release.

Both are applied in the tool's own module, under `@tool()`, so the generated docs
see the same description and signature the server registers.
"""

import functools
import inspect
import types
import typing
from dataclasses import dataclass
from typing import Annotated, Any

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

DEPRECATION_WARNINGS_KEY = "deprecation_warnings"


@dataclass(frozen=True)
class ToolDeprecation:
    """A tool kept for one release, until `removed_in`, with `use` as its replacement."""

    use: str
    removed_in: str


def deprecation_doc(note: str, doc: str | None) -> str:
    """`doc` with `note` as its first paragraph. The original is dedented first, so
    the result reads as one docstring, not a note over an indented block."""
    body = inspect.cleandoc(doc or "")
    return f"{note}\n\n{body}".rstrip()


# Set by `server.tool()` on what it returns, so a deprecation decorator written above
# `@tool()`, which would wrap a tool already registered without its change, fails at
# import instead of silently doing nothing.
REGISTERED_MARK = "__registered_tool__"


def _require_under_tool(decorator_name: str, func) -> None:
    if getattr(func, REGISTERED_MARK, False):
        raise TypeError(
            f"{decorator_name} on {func.__name__}: apply it under @tool(), not above it; "
            "above it, the tool is already registered without the change"
        )


def deprecated_tool(*, use: str, removed_in: str):
    """Mark a tool for removal in `removed_in`; `use` says what replaces it, in the
    words the description should show (e.g. "`share_file`")."""

    def decorator(func):
        _require_under_tool("deprecated_tool", func)
        func.__doc__ = deprecation_doc(
            f"Deprecated: use {use} instead. Removed in {removed_in}.", func.__doc__
        )
        func.__tool_deprecation__ = ToolDeprecation(use, removed_in)
        return func

    return decorator


def tool_deprecation(func) -> ToolDeprecation | None:
    """The deprecation `deprecated_tool` put on `func`, if any."""
    return getattr(func, "__tool_deprecation__", None)


def with_deprecation_warnings(result: dict, warnings: list[str]) -> dict:
    """A copy of `result` with `warnings` added to its `DEPRECATION_WARNINGS_KEY`
    list. For a tool that keeps a removed parameter for a release, which has no
    decorator: there's nothing to map it to, so the tool decides what it does."""
    if not warnings:
        return result
    return {
        **result,
        DEPRECATION_WARNINGS_KEY: [*result.get(DEPRECATION_WARNINGS_KEY, []), *warnings],
    }


def _returns_open_dict(annotation) -> bool:
    """Whether every result annotated `annotation` can take one more key without
    failing its output schema: bare `dict` or `dict[str, Any]`. Not `| None`, since a
    `None` result would drop the warning."""
    if annotation is dict:
        return True
    return typing.get_origin(annotation) is dict and typing.get_args(annotation)[1:] == (Any,)


def _split_annotated(annotation) -> tuple[Any, tuple]:
    """`annotation`'s type and its `Annotated` metadata (descriptions, constraints)."""
    if annotation is inspect.Parameter.empty:
        return Any, ()
    if typing.get_origin(annotation) is Annotated:
        base, *metadata = typing.get_args(annotation)
        return base, tuple(metadata)
    return annotation, ()


def _optional(annotation, *extra) -> Any:
    """`annotation` widened to allow `None`, keeping its metadata outside the union so
    a description or constraint stays on the schema property, not inside one `anyOf`
    branch. `extra` metadata goes last, so it wins where it overlaps."""
    base, metadata = _split_annotated(annotation)
    if not (metadata or extra):
        return base | None
    return Annotated[(base | None, *metadata, *extra)]


def _allows_none(annotation) -> bool:
    base, _ = _split_annotated(annotation)
    if base is Any or base is None or base is type(None):
        return True
    if typing.get_origin(base) in (typing.Union, types.UnionType):
        return any(_allows_none(member) for member in typing.get_args(base))
    return False


def renamed_params(*, removed_in: str, **old_to_new: str):
    """Accept each old parameter name in `old_to_new` (old -> new) until `removed_in`.

    The tool's signature gains each old name as an optional keyword, described as
    deprecated, so strict argument checking still accepts it. A call that passes the
    old name runs as if it passed the new one, and its result gains a warning under
    `DEPRECATION_WARNINGS_KEY`. Passing both is an error, unless the new one is at
    its default (mcp fills defaults in before the call, so that's indistinguishable
    from not passing it). A new parameter with no
    default becomes optional in the schema, since a caller may pass the old name
    instead, and a call that passes neither is an error.

    The tool must return `dict[str, Any]` (or bare `dict`), the one result shape the
    warning can join without breaking its output schema; anything else raises
    TypeError at import. So does a required new parameter whose type allows `None`,
    since an explicit `null` would read as not passed, and so do two old names for
    one new one, since a call passing both would be told to pass only the new one.
    It must be applied under `@tool()`, which `REGISTERED_MARK` enforces.
    """
    if not old_to_new:
        raise ValueError("renamed_params needs at least one old=new pair")
    targets = list(old_to_new.values())
    if duplicates := sorted({new for new in targets if targets.count(new) > 1}):
        raise ValueError(
            f"renamed_params: more than one old name for {', '.join(duplicates)}; "
            "keep one old name per parameter"
        )

    def decorator(func):
        _require_under_tool("renamed_params", func)
        sig = inspect.signature(func, eval_str=True)
        params = dict(sig.parameters)
        if not _returns_open_dict(sig.return_annotation):
            raise TypeError(
                f"renamed_params on {func.__name__}: the tool must return dict[str, Any] "
                "so the deprecation warning can go in its result"
            )
        for old, new in old_to_new.items():
            if new not in params:
                raise TypeError(f"renamed_params on {func.__name__}: no parameter {new!r}")
            if old in params:
                raise TypeError(f"renamed_params on {func.__name__}: {old!r} is still a parameter")
        required = {
            new for new in old_to_new.values() if params[new].default is inspect.Parameter.empty
        }
        for new in sorted(required):
            if _allows_none(params[new].annotation):
                raise TypeError(
                    f"renamed_params on {func.__name__}: required {new!r} allows None, so an "
                    "explicit null couldn't be told from a missing argument; give it a default"
                )

        published = []
        for name, param in params.items():
            if name in required:
                param = param.replace(annotation=_optional(param.annotation), default=None)
            published.append(param.replace(kind=inspect.Parameter.KEYWORD_ONLY))
        for old, new in old_to_new.items():
            note = f"Deprecated: use `{new}`. Removed in {removed_in}."
            published.append(
                inspect.Parameter(
                    old,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=None,
                    annotation=_optional(params[new].annotation, Field(description=note)),
                )
            )

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # A direct positional call (tests, other modules) names its arguments too.
            kwargs = {**sig.bind_partial(*args).arguments, **kwargs}
            warnings = []
            for old, new in old_to_new.items():
                value = kwargs.pop(old, None)
                if value is None:
                    continue
                # mcp fills in a parameter's default before the call, so a new name
                # still at its default counts as not passed.
                if kwargs.get(new) not in (None, params[new].default):
                    raise ToolError(f"Pass only `{new}`: `{old}` is its deprecated old name.")
                kwargs[new] = value
                warnings.append(
                    f"`{old}` is deprecated: use `{new}`. `{old}` is removed in {removed_in}."
                )
            for new in required:
                if kwargs.get(new) is None:
                    raise ToolError(f"Missing required argument `{new}`.")
            return with_deprecation_warnings(await func(**kwargs), warnings)

        wrapper.__signature__ = sig.replace(parameters=published)  # pyright: ignore[reportAttributeAccessIssue]
        return wrapper

    return decorator
