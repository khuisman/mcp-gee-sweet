from contextlib import AbstractContextManager
from typing import Any

from ...auth import invalidating


def doc_invalidating(doc_cache: Any, doc_id: str) -> AbstractContextManager[None]:
    """`invalidating` around a Docs edit's write requests: marks `doc_id` dirty in
    `doc_cache` on every exit but a 4xx, and again once an abandoned request lands
    (#1030). Every Docs edit tool outside content.py/images.py uses it, so the rules
    live in `invalidating` alone."""
    return invalidating(lambda: doc_cache.mark_dirty(doc_id))
