# fastqueue

A small, dependency-free job queue for Python services.

[![Build](https://img.shields.io/badge/build-passing-brightgreen)](https://example.com/ci)

## Features

- In-process or Redis-backed storage
- Retries with exponential backoff
- Scheduled jobs (`run_at=`)
- Type-annotated API

## Installation

```bash
pip install fastqueue
```

For Redis support:

```bash
pip install "fastqueue[redis]"
```

## Quick start

```python
from fastqueue import Queue

q = Queue()

@q.job(retries=3)
def send_email(to: str, subject: str) -> None:
    ...

send_email.delay("user@example.com", "Welcome!")
q.run_worker()
```

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `backend` | `"memory"` | `"memory"` or `"redis"` |
| `redis_url` | `None` | Required when `backend="redis"` |
| `max_retries` | `5` | Upper bound for any job |
| `poll_interval` | `0.5` | Seconds between polls |

## Usage notes

1. Jobs must be importable by the worker process.
2. Arguments must be JSON-serializable.
3. Use `q.job(timeout=...)` for long-running work:
   ```python
   @q.job(timeout=300)
   def rebuild_index(): ...
   ```
4. Call `q.shutdown()` on exit to flush pending acks.

> **Note:** the in-memory backend loses jobs when the process exits. Use Redis
> in production.

## Contributing

PRs are welcome. Please run `make test` and `make lint` before opening one, and
see [CONTRIBUTING.md](https://example.com/contributing) for details.

## License

MIT © 2026 fastqueue contributors
