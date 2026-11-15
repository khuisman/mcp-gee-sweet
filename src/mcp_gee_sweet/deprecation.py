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


def deprecated_tool(*, use: str, removed_in: str):
    """Mark a tool for removal in `removed_in`; `use` says what replaces it, in the
    words the description should show (e.g. "`share_file`")."""

    def decorator(func):
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
    """Whether a result annotated `annotation` can take one more key without failing
    its output schema: bare `dict`, `dict[str, Any]`, or either with `| None`."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        members = [a for a in typing.get_args(annotation) if a is not type(None)]
        return len(members) == 1 and _returns_open_dict(members[0])
    if annotation is dict:
        return True
    return origin is dict and typing.get_args(annotation)[1:] == (Any,)


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
    TypeError at import.
    """
    if not old_to_new:
        raise ValueError("renamed_params needs at least one old=new pair")

    def decorator(func):
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

        published = []
        for name, param in params.items():
            if name in required:
                annotation = (
                    Any if param.annotation is inspect.Parameter.empty else param.annotation
                )
                param = param.replace(annotation=annotation | None, default=None)
            published.append(param.replace(kind=inspect.Parameter.KEYWORD_ONLY))
        for old, new in old_to_new.items():
            annotation = params[new].annotation
            if annotation is inspect.Parameter.empty:
                annotation = Any
            note = f"Deprecated: use `{new}`. Removed in {removed_in}."
            published.append(
                inspect.Parameter(
                    old,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=None,
                    annotation=Annotated[annotation | None, Field(description=note)],
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
            result = await func(**kwargs)
            if isinstance(result, dict):
                result = with_deprecation_warnings(result, warnings)
            return result

        wrapper.__signature__ = sig.replace(parameters=published)  # pyright: ignore[reportAttributeAccessIssue]
        return wrapper

    return decorator
