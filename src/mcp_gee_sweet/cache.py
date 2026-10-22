import contextlib
import json
import logging
import os
import sqlite3
import stat
import sys
import time
from dataclasses import dataclass
from typing import Any

import httplib2
from google.auth.exceptions import TransportError
from googleapiclient.errors import HttpError

from .http_transport import execute_in_thread

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: str) -> bool:
    """Parse a boolean env var via an allowlist of truthy values.

    An unrecognized or misspelled value (e.g. "off", "disabled") falls back to
    disabled rather than silently staying enabled.
    """
    return os.environ.get(name, default).strip().lower() in ("true", "1", "yes", "y", "on")


def default_db_path(environ=os.environ, platform: str = sys.platform) -> str:
    """The cache DB's default location, in this user's own cache directory: Windows
    %LOCALAPPDATA%, macOS ~/Library/Caches, elsewhere an absolute $XDG_CACHE_HOME or
    ~/.cache, then mcp-gee-sweet/cache.db (GHSA-8jqx-w7j8-6xwm). Pure: creates
    nothing. With no resolvable home directory the result isn't absolute, and the
    first open falls back to an in-memory cache (`_prepare`)."""
    home = os.path.expanduser("~")
    if platform == "win32":
        base = environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    elif platform == "darwin":
        base = os.path.join(home, "Library", "Caches")
    else:
        xdg = environ.get("XDG_CACHE_HOME", "")
        # The XDG spec says to ignore a relative value.
        base = xdg if os.path.isabs(xdg) else os.path.join(home, ".cache")
    return os.path.join(base, "mcp-gee-sweet", "cache.db")


def db_path(environ=os.environ, platform: str = sys.platform) -> str:
    """CACHE_DB_PATH if set and non-empty (":memory:" included), else the default."""
    return environ.get("CACHE_DB_PATH") or default_db_path(environ, platform)


CACHE_DB_PATH = db_path()
CACHE_TTL = int(os.environ.get("CACHE_TTL", "1800"))  # 30 minutes
# When enabled, a cache hit for sheet structure/data or doc content is validated
# against the source file's Drive modifiedTime before being served, so edits from
# other users/tabs are picked up without waiting out the TTL. Costs one extra
# Drive API call per cache lookup — disable if that overhead outweighs the benefit.
CACHE_VALIDATE_MODIFIED_TIME = _env_flag("CACHE_VALIDATE_MODIFIED_TIME", "true")

# The pre-GHSA-8jqx default: one world-readable file in /tmp shared by every user.
# Never migrated or deleted, only tightened (`_tighten_legacy_db`).
_LEGACY_DB_PATH = "/tmp/mcp_gee_sweet.db"
_legacy_db_checked = False

# Bumped when the table's shape changes. A DB at another version has its table
# dropped and recreated at open: nothing is migrated (it's a cache).
_SCHEMA_VERSION = 2

# `principal` is the Google identity the row was fetched as (see auth.py's
# ensure_cache_principal): a read only ever sees its own principal's rows.
_DDL = """
CREATE TABLE IF NOT EXISTS cache (
    principal    TEXT NOT NULL,
    namespace    TEXT NOT NULL,
    key          TEXT NOT NULL,
    value        TEXT NOT NULL,
    fetched_at   REAL NOT NULL,
    dirty        INTEGER NOT NULL DEFAULT 0,
    rows_fetched INTEGER,
    PRIMARY KEY (principal, namespace, key)
)
"""

_SIDECARS = ("", "-wal", "-shm")
# Windows has no POSIX owner or mode bits to check.
_POSIX = os.name != "nt"


class _CacheFileRefused(OSError):
    """A cache file or directory this process mustn't use (another user's, or a
    symlink). `_open` falls back to an in-memory cache without touching it."""


def _check_own_file(path: str) -> None:
    """Refuse `path` if it exists and isn't a regular file owned by this user."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(st.st_mode):
        raise _CacheFileRefused(f"{path} isn't a regular file")
    if _POSIX and st.st_uid != os.getuid():
        raise _CacheFileRefused(f"{path} is owned by another user")


def _prepare_dir(directory: str) -> None:
    """Create the default cache directory owner-only, and check an existing one: a
    real directory, owned by this user, tightened to 0700 if it has group or other
    bits."""
    os.makedirs(directory, mode=0o700, exist_ok=True)
    st = os.lstat(directory)
    if not stat.S_ISDIR(st.st_mode):
        raise _CacheFileRefused(f"{directory} isn't a directory")
    if not _POSIX:
        return
    if st.st_uid != os.getuid():
        raise _CacheFileRefused(f"{directory} is owned by another user")
    if st.st_mode & 0o077:
        os.chmod(directory, 0o700)


def _prepare(path: str) -> None:
    """Before connecting to a file DB: set up its directory (the default location
    only; an explicit CACHE_DB_PATH's directory is left alone), then create the DB
    file owner-only without following a symlink, and refuse one that isn't ours.
    Raises OSError (`_CacheFileRefused` for a refusal)."""
    if path == default_db_path():
        if not os.path.isabs(path):
            raise _CacheFileRefused("no home directory to put the cache in")
        _prepare_dir(os.path.dirname(path))
        _tighten_legacy_db()
    for suffix in _SIDECARS:
        _check_own_file(path + suffix)
    # Ours (or absent), so make it owner-only now: that also repairs a read-only one.
    _tighten_files(path)
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError as e:
        if os.path.islink(path):
            raise _CacheFileRefused(f"{path} is a symlink") from e
        raise
    try:
        st = os.fstat(fd)
    finally:
        os.close(fd)
    if _POSIX and st.st_uid != os.getuid():
        raise _CacheFileRefused(f"{path} is owned by another user")


def _chmod_own_file(path: str, mode: int) -> None:
    """chmod `path` if it's a regular file owned by this user and looser than `mode`;
    anything else (absent, a symlink, another user's) is left alone. Checked with
    lstat, then a plain chmod: `chmod(follow_symlinks=False)` raises
    NotImplementedError on glibc < 2.32 (RHEL 8, Ubuntu 20.04, Debian 11)."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
        return
    if stat.S_IMODE(st.st_mode) & ~mode:
        os.chmod(path, mode)


def _tighten_files(path: str) -> None:
    """chmod the DB and its WAL sidecars to 0600: a file created before this rule,
    or a sidecar SQLite created under a looser umask."""
    if not _POSIX:
        return
    for suffix in _SIDECARS:
        _chmod_own_file(path + suffix, 0o600)


def _tighten_legacy_db() -> None:
    """Once per process: make the old shared /tmp DB owner-only if it's ours. It
    may still hold cached Google data readable by every local user (decision A on
    GHSA-8jqx-w7j8-6xwm). Never deleted: the release notes tell users to."""
    global _legacy_db_checked
    if _legacy_db_checked or not _POSIX:
        return
    _legacy_db_checked = True
    for suffix in _SIDECARS:
        with contextlib.suppress(OSError):
            _chmod_own_file(_LEGACY_DB_PATH + suffix, 0o600)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Recreate the table if the DB is at another schema version. Checked again
    under the write lock, so two processes opening an old DB at once drop it once."""
    if conn.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_VERSION:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("PRAGMA user_version").fetchone()[0] != _SCHEMA_VERSION:
            conn.execute("DROP TABLE IF EXISTS cache")
            conn.execute(_DDL)
            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


_WAL_RETRY_SECONDS = 5.0


def _enable_wal(conn: sqlite3.Connection) -> None:
    """Switch to WAL, retrying while another opener holds the file. Switching a new
    DB's journal mode needs a lock SQLite won't wait for (the busy handler isn't
    called), so two processes opening it at once can get "database is locked",
    which _open would answer by deleting the file. A no-op once the file is WAL."""
    deadline = time.monotonic() + _WAL_RETRY_SECONDS
    while True:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) or time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def _connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        _prepare(path)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        conn.row_factory = sqlite3.Row
        # Concurrent Claude sessions share this DB file by default; without a busy_timeout
        # a write from another session hits SQLITE_BUSY immediately instead of waiting.
        conn.execute("PRAGMA busy_timeout=5000")
        _enable_wal(conn)
        _ensure_schema(conn)
        if path != ":memory:":
            _tighten_files(path)
    except BaseException:
        conn.close()
        raise
    return conn


def _open(db_path: str) -> sqlite3.Connection:
    # Each cache class holds its own connection to the same DB file. WAL mode lets
    # them read concurrently without blocking each other. All cache I/O is synchronous
    # on the asyncio event loop — deliberately NOT wrapped in asyncio.to_thread(), even
    # though tool code now runs concurrent .execute() calls via asyncio.gather() (#183).
    # A sync call here only ever runs on the single event-loop thread, interleaved
    # between awaits, so it can never race with another coroutine's cache access —
    # wrapping it in to_thread() would introduce real OS-thread concurrency against
    # this connection with no lock protecting it. Leave this synchronous.
    try:
        return _connect(db_path)
    except OSError as exc:
        # Another user's file or directory, a symlink, or a directory that can't be
        # created (e.g. a container user with no home). Never deleted.
        logger.warning("Cache file not usable (%s), falling back to :memory:", exc)
    except sqlite3.OperationalError as exc:
        # Stale/read-only/corrupted files (e.g. left by Docker with wrong perms).
        # Try deleting and recreating; if that also fails, fall back to :memory:.
        if db_path != ":memory:":
            for suffix in ("", "-shm", "-wal"):
                path = db_path + suffix
                with contextlib.suppress(OSError):
                    os.remove(path)
            logger.warning("Cache file unusable (%s), deleted and retrying: %s", exc, db_path)
            try:
                return _connect(db_path)
            except (OSError, sqlite3.OperationalError) as exc2:
                logger.warning("Cache file still unusable (%s), falling back to :memory:", exc2)
        else:
            logger.warning("In-memory cache failed to initialise (%s)", exc)
    return _connect(":memory:")


def _safe_fetchone(conn: sqlite3.Connection, sql: str, params: tuple) -> sqlite3.Row | None:
    """Run a SELECT and fetchone(), treating any sqlite error as a cache miss.

    Another session's crash can leave a locked/corrupted WAL behind; a cache read
    should never take down a tool call over it (fail open, same as the API-fetch
    fallback in fetch_sheets()).
    """
    try:
        return conn.execute(sql, params).fetchone()
    except sqlite3.Error as exc:
        logger.warning("Cache read failed (%s), treating as cache miss", exc)
        return None


def _safe_write(conn: sqlite3.Connection, sql: str, params: tuple) -> int:
    """Run a write statement + commit, swallowing sqlite errors (fail-open cache write).

    A failed cache write must not fail the tool call that already succeeded against
    the underlying Google API — it just means that result won't be cached this time.
    Returns the affected row count (0 on error, or when a conditional upsert declined).
    """
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount
    except sqlite3.Error as exc:
        logger.warning("Cache write failed (%s), continuing without caching", exc)
        return 0


# Stored as `rows_fetched` when a fetch is known to have returned *everything* there
# was (a Drive listing with no nextPageToken and no incompleteSearch flag),
# so any later request size — however large — is satisfied by it. SQLite's INTEGER
# max, so the ordinary `rows_fetched >= requested` comparison needs no special case.
ROWS_EXHAUSTIVE = 2**63 - 1

_REPLACE_SQL = (
    "INSERT OR REPLACE INTO cache (principal, namespace, key, value, fetched_at, dirty)"
    " VALUES (?,?,?,?,?,0)"
)

_SIZED_UPSERT_SQL = (
    "INSERT INTO cache (principal, namespace, key, value, fetched_at, dirty, rows_fetched)"
    " VALUES (?,?,?,?,?,0,?)"
    " ON CONFLICT(principal, namespace, key) DO UPDATE SET"
    " value=excluded.value, fetched_at=excluded.fetched_at, dirty=0,"
    " rows_fetched=excluded.rows_fetched"
    # Compare-and-set: never let a smaller fetch clobber a larger, still-valid one
    # just because it finished later (#698) — only replace a row that's already
    # invalid (dirty or TTL-expired) or no larger than what's being written.
    " WHERE cache.dirty=1 OR cache.fetched_at < ?"
    " OR COALESCE(cache.rows_fetched, 0) <= excluded.rows_fetched"
)


async def get_modified_time(drive_service: Any, file_id: str) -> str | None:
    """Fetch a Drive file's modifiedTime, or None if unavailable/on any failure.

    Used to validate a cache hit against the live source before serving it —
    a lightweight `fields=modifiedTime`-only call, distinct from the full
    metadata fetch a cache miss triggers.
    """
    if drive_service is None:
        return None
    try:
        meta = await execute_in_thread(
            drive_service.files()
            .get(fileId=file_id, fields="modifiedTime", supportsAllDrives=True)
            .execute,
            drive_service,
        )
        return meta.get("modifiedTime")
    except Exception as e:
        # Any failure here (auth error, 404, rate limit, timeout) silently falls
        # back to plain TTL caching for this lookup — the exact staleness risk
        # this feature exists to close. Log at WARNING so it's operator-visible
        # instead of indistinguishable from "validation intentionally disabled".
        logger.warning(
            "Could not fetch modifiedTime for %s, falling back to TTL only: %s", file_id, e
        )
        return None


class _Invalidations:
    """In-memory only (not persisted): when each exact key, key prefix, or the whole
    namespace was last invalidated, as values of a monotonic counter bumped on every
    invalidation. A read that snapshots the counter before an async fetch and passes
    it to store() afterward lets store() detect whether a refresh_cache() (or any
    other invalidation) landed *during* that fetch's await, and skip overwriting
    dirty=1 with stale-relative-to-the-invalidation data. Per key, so a store is only
    rejected by an invalidation that covers its own key, not one for an unrelated
    folder or spreadsheet in the same namespace (#698). Grows with the number of
    distinct keys ever invalidated in this process: one int per key, negligible.

    Its own object, not fields of a cache instance, so a rebound replacement shares
    it with the instance it replaces (`auth._bind_caches`)."""

    def __init__(self):
        self.epoch = 0
        self._keys: dict[str, int] = {}
        self._prefixes: dict[str, int] = {}
        self._all = 0

    def key(self, key: str) -> None:
        self.epoch += 1
        self._keys[key] = self.epoch

    def prefix(self, prefix: str) -> None:
        self.epoch += 1
        self._prefixes[prefix] = self.epoch

    def all(self) -> None:
        self.epoch += 1
        self._all = self.epoch

    def covers(self, key: str, epoch: int) -> bool:
        """True if an invalidation covering `key` happened after `epoch` was snapshot.
        Prefixes are `<id>:`, so only the key's own `:`-delimited leading segments
        can match — checked directly rather than scanning every recorded prefix."""
        if self._all > epoch or self._keys.get(key, 0) > epoch:
            return True
        start = 0
        while (i := key.find(":", start)) != -1:
            if self._prefixes.get(key[: i + 1], 0) > epoch:
                return True
            start = i + 1
        return False


class _BaseCache:
    """Shared connection/TTL/dirty-marking plumbing for the five cache namespaces.

    Subclasses set `_NS` and provide their own `get`/`store` methods (key shape and
    cached payload shape differ per namespace), built on the shared pieces here:
    the modifiedTime-comparison and TTL-expiry checks, the epoch-guarded write
    (`_store_if_fresh`), and — for caches bounded by a row/result count — the
    `_get_sized`/`_store_sized` pair, so that fixing one (e.g. a staleness bug)
    doesn't require hunting down near-identical copies.

    Each instance is bound to one fixed `principal`, the Google identity its
    entries were fetched as (GHSA-8jqx-w7j8-6xwm): reads and writes see only that
    principal's rows. Unbound (`None`), a read always misses and a write does
    nothing. Invalidation (`mark_dirty`, `mark_all_dirty`) is deliberately not
    scoped to the principal: a change one identity made is stale for every other.
    Rebinding means replacing the instance, never mutating it, so a fetch already
    in flight stores under the principal it was fetched as. The replacement shares
    the old instance's `invalidations`, so an invalidation on either one still
    stops that in-flight store (#698's guard spans the rebind).

    The DB connection opens at first use, not at construction: a context's
    default (unbound) instances are replaced by bound ones once its identity
    resolves, so they open the DB only if it never does.
    """

    _NS: str

    def __init__(
        self,
        db_path: str | None = None,
        ttl: int = CACHE_TTL,
        principal: str | None = None,
        invalidations: _Invalidations | None = None,
    ):
        self._db_path = CACHE_DB_PATH if db_path is None else db_path
        self._ttl = ttl
        self._principal = principal
        self._connection: sqlite3.Connection | None = None
        self.invalidations = invalidations if invalidations is not None else _Invalidations()

    @property
    def _conn(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = _open(self._db_path)
            opened = self._connection.execute("PRAGMA database_list").fetchone()[2]
            # The path actually in use: after a refusal it's in-memory, not db_path.
            logger.debug("%s cache opened: %s", self._NS, opened or ":memory:")
        return self._connection

    def set_ttl(self, ttl: int) -> None:
        self._ttl = ttl

    def get_ttl(self) -> int:
        return self._ttl

    @property
    def principal(self) -> str | None:
        return self._principal

    def _fetch_row(self, columns: str, key: str) -> sqlite3.Row | None:
        """This principal's row for `key`, or None (always None when unbound)."""
        if self._principal is None:
            return None
        return _safe_fetchone(
            self._conn,
            f"SELECT {columns} FROM cache WHERE principal=? AND namespace=? AND key=?",
            (self._principal, self._NS, key),
        )

    def _replace(self, key: str, value: Any, epoch: int | None = None) -> bool:
        """Write `value` as this principal's entry for `key`, unconditionally apart
        from the epoch guard. Does nothing when unbound. Returns whether it wrote."""
        return self._store_if_fresh(
            key,
            _REPLACE_SQL,
            (self._principal, self._NS, key, json.dumps(value), time.time()),
            epoch,
        )

    def close(self):
        """Close the connection. Safe on a never-used instance, and a later read or
        write on a closed one is a miss or a dropped write (`_safe_*`), not a crash:
        a fetch still in flight may hold a replaced instance."""
        if self._connection is None:
            self._connection = sqlite3.connect(":memory:", check_same_thread=False)
        self._connection.close()

    def __del__(self):
        # A rebound instance is dropped, not closed (auth._bind_caches): close its
        # connection once nothing holds it, rather than leaving it to sqlite3's
        # finalizer (a ResourceWarning on 3.13+).
        if (connection := getattr(self, "_connection", None)) is not None:
            with contextlib.suppress(Exception):
                connection.close()

    def snapshot_epoch(self) -> int:
        """Call before starting a fetch that will later call store(); pass the result
        as store()'s `epoch` kwarg so it can detect a concurrent invalidation."""
        return self.invalidations.epoch

    def _invalidated_since(self, key: str, epoch: int) -> bool:
        return self.invalidations.covers(key, epoch)

    def _store_if_fresh(self, key: str, sql: str, params: tuple, epoch: int | None) -> bool:
        """Run a cache write for `key` unless an invalidation covering it happened after
        the caller's snapshot_epoch() call. Returns whether it wrote (a conditional
        upsert that declined also counts as not written). Never writes when unbound.
        """
        if self._principal is None:
            return False
        if epoch is not None and self._invalidated_since(key, epoch):
            logger.debug("%s cache store skipped for %s — invalidated during fetch", self._NS, key)
            return False
        return _safe_write(self._conn, sql, params) > 0

    def _get_sized(
        self, key: str, requested: int, current_modified_time: str | None = None
    ) -> Any | None:
        """Shared read for size-bounded caches (a fetch limited by a row/result count).

        Returns the decoded cached value, or None on miss/dirty/stale-vs-source/
        expired/insufficient prior fetch size. The size parameter
        (`max_results`/`rows_to_fetch`) is deliberately not part of the key: an entry
        records how many results the fetch that produced it asked for (or
        ROWS_EXHAUSTIVE if it got everything), and a request is a hit only if that
        covers what it's asking for now — the caller slices the value down to size.
        Keying on the count instead would either serve a larger cached result
        unsliced or let a small fetch poison the entry for a later larger one (#688).
        """
        row = self._fetch_row("value, fetched_at, dirty, rows_fetched", key)
        if row is None or row["dirty"]:
            return None
        if not self._check_ttl(row["fetched_at"], key):
            return None
        value = None
        if current_modified_time is not None:
            # Checked before the size test (not after) so a stale-vs-source entry
            # gets marked dirty even when this request is too large for it — else
            # the refetch's compare-and-set store would decline to replace it.
            value = json.loads(row["value"])
            if not self._check_modified_time(value, current_modified_time, key):
                return None
        if (row["rows_fetched"] or 0) < requested:
            return None
        return value if value is not None else json.loads(row["value"])

    def _store_sized(
        self, key: str, value: Any, requested: int, exhaustive: bool, epoch: int | None
    ) -> bool:
        """Shared write for size-bounded caches — see `_get_sized`. Epoch-guarded like
        `_store_if_fresh`, plus a compare-and-set that keeps a larger still-valid
        entry over a smaller one. Returns whether it wrote."""
        now = time.time()
        return self._store_if_fresh(
            key,
            _SIZED_UPSERT_SQL,
            (
                self._principal,
                self._NS,
                key,
                json.dumps(value),
                now,
                ROWS_EXHAUSTIVE if exhaustive else requested,
                now - self._ttl,
            ),
            epoch,
        )

    def _mark_dirty_key(self, key: str, invalidate_in_flight: bool = True) -> None:
        """`invalidate_in_flight=False` is for TTL expiry: an entry aging out isn't a
        change a concurrent fetch's result predates, so it mustn't block that store.
        Expiry is this principal's own row aging out, so it marks only that row; any
        other invalidation marks every principal's row for `key`."""
        if invalidate_in_flight:
            _safe_write(
                self._conn,
                "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?",
                (self._NS, key),
            )
            self.invalidations.key(key)
        else:
            _safe_write(
                self._conn,
                "UPDATE cache SET dirty=1 WHERE principal=? AND namespace=? AND key=?",
                (self._principal, self._NS, key),
            )

    def _mark_dirty_prefix(self, prefix: str) -> None:
        """Mark every key starting with `prefix` (an `<id>:`) dirty, and record the
        invalidation so an in-flight fetch for a covered key can't overwrite it (#698).
        Uses substr rather than LIKE so a `_`/`%` in a Drive/Sheets ID isn't read as a
        wildcard."""
        _safe_write(
            self._conn,
            "UPDATE cache SET dirty=1 WHERE namespace=? AND substr(key, 1, ?)=?",
            (self._NS, len(prefix), prefix),
        )
        self.invalidations.prefix(prefix)

    def mark_all_dirty(self):
        _safe_write(self._conn, "UPDATE cache SET dirty=1 WHERE namespace=?", (self._NS,))
        self.invalidations.all()
        logger.debug("Invalidated all %s cache entries", self._NS)

    def _check_modified_time(
        self, value: dict, current_modified_time: str | None, key: str
    ) -> bool:
        """True if the cached value is still valid re: modifiedTime (or n/a).

        False means it was stale and has already been marked dirty.
        """
        if current_modified_time is None:
            return True
        cached_mtime = value.get("modified_time")
        if cached_mtime is not None and cached_mtime != current_modified_time:
            logger.debug("Source modified since cache for %s, marking dirty", key)
            self._mark_dirty_key(key)
            return False
        return True

    def _check_ttl(self, fetched_at: float, key: str) -> bool:
        """True if fetched_at is still within TTL; False means expired+marked dirty."""
        if time.time() - fetched_at > self._ttl:
            logger.debug("Cache TTL expired for %s, marking dirty", key)
            self._mark_dirty_key(key, invalidate_in_flight=False)
            return False
        return True


@dataclass
class SheetInfo:
    title: str
    sheet_id: int


class SheetStructureCache(_BaseCache):
    _NS = "sheet_structure"

    def _get_valid(
        self, spreadsheet_id: str, current_modified_time: str | None = None
    ) -> dict | None:
        row = self._fetch_row("value, fetched_at, dirty", spreadsheet_id)
        if row is None or row["dirty"]:
            return None
        value = json.loads(row["value"])
        if not self._check_modified_time(value, current_modified_time, spreadsheet_id):
            return None
        if not self._check_ttl(row["fetched_at"], spreadsheet_id):
            return None
        return value

    def get_sheets(
        self, spreadsheet_id: str, current_modified_time: str | None = None
    ) -> list[SheetInfo] | None:
        """Returns cached sheet list, or None on cache miss/dirty/expired/stale-vs-source."""
        value = self._get_valid(spreadsheet_id, current_modified_time)
        if value is None:
            return None
        return [SheetInfo(**s) for s in value["sheets"]]

    def get_title(
        self, spreadsheet_id: str, current_modified_time: str | None = None
    ) -> str | None:
        """Returns cached spreadsheet title, or None on cache miss/dirty/expired/stale-vs-source."""
        value = self._get_valid(spreadsheet_id, current_modified_time)
        if value is None:
            return None
        return value.get("title")

    def store(
        self,
        spreadsheet_id: str,
        sheets: list[SheetInfo],
        title: str | None = None,
        modified_time: str | None = None,
        epoch: int | None = None,
    ):
        value: dict = {"sheets": [{"title": s.title, "sheet_id": s.sheet_id} for s in sheets]}
        if title is not None:
            value["title"] = title
        if modified_time is not None:
            value["modified_time"] = modified_time
        if self._replace(spreadsheet_id, value, epoch):
            logger.debug("Cached %d sheets for %s", len(sheets), spreadsheet_id)

    def mark_dirty(self, spreadsheet_id: str):
        self._mark_dirty_key(spreadsheet_id)
        logger.debug("Marked cache dirty for %s", spreadsheet_id)

    def get_stale_sheets(self, spreadsheet_id: str) -> list[SheetInfo] | None:
        """Returns this principal's cached sheet list regardless of dirty/TTL state;
        None on a complete miss or when unbound."""
        row = self._fetch_row("value", spreadsheet_id)
        if row is None:
            return None
        return [SheetInfo(**s) for s in json.loads(row["value"])["sheets"]]


class SheetDataCache(_BaseCache):
    """Caches per-sheet summary data (headers + first N rows) keyed by (spreadsheet_id, sheet_id)."""

    _NS = "sheet_data"

    def _key(self, spreadsheet_id: str, sheet_id: int) -> str:
        return f"{spreadsheet_id}:{sheet_id}"

    def get(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        rows_to_fetch: int,
        current_modified_time: str | None = None,
    ) -> dict | None:
        """Returns cached {headers, first_rows}, or None on miss/dirty/expired/insufficient rows/stale-vs-source."""
        value = self._get_sized(
            self._key(spreadsheet_id, sheet_id), rows_to_fetch, current_modified_time
        )
        if value is None:
            return None
        logger.debug("Sheet data cache hit: %s/%s", spreadsheet_id, sheet_id)
        return {
            "headers": value["headers"],
            "first_rows": value["first_rows"][: max(1, rows_to_fetch) - 1],
        }

    def store(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        headers: list,
        first_rows: list,
        rows_to_fetch: int,
        modified_time: str | None = None,
        epoch: int | None = None,
    ):
        # Never exhaustive: a values().get on A1:N shorter than N rows only means rows
        # up to N are trailing-empty, not that the sheet has no data further down
        # (a gap of empty rows followed by more data) — PR #788 QA round 1.
        value: dict = {"headers": headers, "first_rows": first_rows}
        if modified_time is not None:
            value["modified_time"] = modified_time
        wrote = self._store_sized(
            self._key(spreadsheet_id, sheet_id), value, rows_to_fetch, False, epoch
        )
        if wrote:
            logger.debug("Cached sheet data for %s/%s", spreadsheet_id, sheet_id)

    def mark_dirty(self, spreadsheet_id: str, sheet_id: int | None = None):
        if sheet_id is not None:
            self._mark_dirty_key(self._key(spreadsheet_id, sheet_id))
            logger.debug("Marked sheet data dirty for %s/%s", spreadsheet_id, sheet_id)
        else:
            self._mark_dirty_prefix(f"{spreadsheet_id}:")
            logger.debug("Marked all sheet data dirty for %s", spreadsheet_id)


class DriveFolderCache(_BaseCache):
    """Caches Drive folder listings keyed by (folder_id, mime_type).

    No modifiedTime-based validation: a folder's own modifiedTime does not
    change when children are added/removed, so it can't detect staleness here.

    Size-bounded by `max_results` via `_BaseCache._get_sized`/`_store_sized` — the
    same sufficiency/epoch/compare-and-set mechanism SheetDataCache uses (#688, #698).
    """

    _NS = "drive_folder"

    def _key(self, folder_id: str, mime_type: str | None) -> str:
        return f"{folder_id}:{mime_type or ''}"

    def get(self, folder_id: str, mime_type: str | None, max_results: int) -> list | None:
        """Returns cached file list (sliced to max_results), or None on miss/dirty/
        expired/insufficient prior fetch size."""
        files = self._get_sized(self._key(folder_id, mime_type), max_results)
        if files is None:
            return None
        logger.debug("Drive folder cache hit: %s (mime=%s)", folder_id, mime_type)
        return files[:max_results]

    def store(
        self,
        folder_id: str,
        mime_type: str | None,
        files: list,
        max_results: int,
        epoch: int | None = None,
        exhaustive: bool = False,
    ):
        """`exhaustive=True` means Drive returned no nextPageToken — the listing is
        complete — so any later, larger `max_results` is a hit."""
        wrote = self._store_sized(
            self._key(folder_id, mime_type), files, max_results, exhaustive, epoch
        )
        if wrote:
            logger.debug(
                "Cached %d files for folder %s (mime=%s)", len(files), folder_id, mime_type
            )

    def mark_dirty(self, folder_id: str):
        self._mark_dirty_prefix(f"{folder_id}:")
        logger.debug("Marked drive folder cache dirty for %s", folder_id)


class DocContentCache(_BaseCache):
    """Caches Google Doc content keyed by file_id."""

    _NS = "doc_content"

    def _get_valid(self, file_id: str, current_modified_time: str | None = None) -> dict | None:
        row = self._fetch_row("value, fetched_at, dirty", file_id)
        if row is None or row["dirty"]:
            return None
        # get_doc_content already stores the source's modifiedTime as part of
        # the cached doc dict — no separate column needed.
        value = json.loads(row["value"])
        if not self._check_modified_time(value, current_modified_time, file_id):
            return None
        if not self._check_ttl(row["fetched_at"], file_id):
            return None
        return value

    def get(self, file_id: str, current_modified_time: str | None = None) -> dict | None:
        """Returns cached doc response dict, or None on miss/dirty/expired/stale-vs-source."""
        value = self._get_valid(file_id, current_modified_time)
        if value is None:
            return None
        logger.debug("Doc cache hit: %s", file_id)
        return value

    def store(self, file_id: str, doc: dict):
        if self._replace(file_id, doc):
            logger.debug("Cached doc %s", file_id)

    def mark_dirty(self, file_id: str):
        self._mark_dirty_key(file_id)
        logger.debug("Marked doc cache dirty for %s", file_id)


class CalendarCache(_BaseCache):
    """Caches calendar list and per-calendar metadata keyed by calendar_id.

    No modifiedTime-based validation: calendars aren't Drive files and don't
    expose a comparable field via the Calendar API; TTL/dirty invalidation only.
    """

    _NS = "calendar"
    _LIST_KEY = "__list__"

    def _get_valid(self, key: str) -> sqlite3.Row | None:
        row = self._fetch_row("value, fetched_at, dirty", key)
        if row is None or row["dirty"]:
            return None
        if not self._check_ttl(row["fetched_at"], key):
            return None
        return row

    def get_list(self) -> list | None:
        """Returns cached calendar list, or None on miss/dirty/expired."""
        row = self._get_valid(self._LIST_KEY)
        if row is None:
            return None
        logger.debug("Calendar list cache hit")
        return json.loads(row["value"])

    def store_list(self, calendars: list):
        if self._replace(self._LIST_KEY, calendars):
            logger.debug("Cached calendar list (%d entries)", len(calendars))

    def get(self, calendar_id: str) -> dict | None:
        """Returns cached calendar metadata, or None on miss/dirty/expired."""
        row = self._get_valid(calendar_id)
        if row is None:
            return None
        logger.debug("Calendar cache hit: %s", calendar_id)
        return json.loads(row["value"])

    def store(self, calendar_id: str, calendar: dict):
        if self._replace(calendar_id, calendar):
            logger.debug("Cached calendar %s", calendar_id)

    def mark_dirty(self, calendar_id: str):
        for key in (calendar_id, self._LIST_KEY):
            self._mark_dirty_key(key)
        logger.debug("Marked calendar cache dirty for %s", calendar_id)


async def fetch_sheets(
    sheets_service: Any,
    spreadsheet_id: str,
    cache: SheetStructureCache,
    drive_service: Any = None,
) -> list[SheetInfo]:
    """Fetch sheet list with caching. Falls back to stale cache if API call fails.

    If drive_service is given and CACHE_VALIDATE_MODIFIED_TIME is enabled, a
    cache hit is validated against the spreadsheet's live Drive modifiedTime
    first — an edit from another session invalidates the cache immediately
    instead of waiting out the TTL.
    """
    current_mtime = (
        await get_modified_time(drive_service, spreadsheet_id)
        if CACHE_VALIDATE_MODIFIED_TIME
        else None
    )
    cached = cache.get_sheets(spreadsheet_id, current_modified_time=current_mtime)
    if cached is not None:
        logger.debug("Cache hit: %d sheets for %s", len(cached), spreadsheet_id)
        return cached

    # Snapshot before the API await so store() can tell whether a concurrent
    # mark_dirty() (e.g. refresh_cache()) landed while this fetch was in flight —
    # if so, store() skips writing rather than silently clearing that invalidation.
    epoch = cache.snapshot_epoch()
    try:
        spreadsheet = await execute_in_thread(
            sheets_service.spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                fields="properties.title,sheets(properties(title,sheetId))",
            )
            .execute,
            sheets_service,
        )
        sheets = [
            SheetInfo(title=s["properties"]["title"], sheet_id=s["properties"]["sheetId"])
            for s in spreadsheet.get("sheets", [])
        ]
        title = spreadsheet.get("properties", {}).get("title")
        cache.store(spreadsheet_id, sheets, title=title, modified_time=current_mtime, epoch=epoch)
        return sheets
    except Exception as e:
        # Fall back to stale cache rather than hard-failing, but only when the API
        # couldn't answer. A 403 or 404 is an answer: serving cached data then would
        # hand it to a caller Google just refused (GHSA-8jqx-w7j8-6xwm).
        if not _is_transient(e):
            raise
        stale = cache.get_stale_sheets(spreadsheet_id)
        if stale is not None:
            logger.warning("API call failed for %s, serving stale cache: %s", spreadsheet_id, e)
            return stale
        raise


def _is_transient(error: Exception) -> bool:
    """Whether `error` means Google couldn't answer (a 5xx, a 429, or a transport
    failure), as opposed to an answer such as a 403/404. A RefreshError isn't
    transient: it must reach #873's re-authorization path."""
    if isinstance(error, HttpError):
        status = getattr(error, "status_code", None) or getattr(error.resp, "status", 0)
        return int(status) >= 500 or int(status) == 429
    return isinstance(error, (httplib2.error.HttpLib2Error, TransportError, TimeoutError, OSError))
