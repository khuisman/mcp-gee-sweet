# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[Semantic Versioning](https://semver.org/).

## [2.4.0] - 2026-10-15

### Added

- `--dry-run` flag for the `deploy` command
- Support for YAML anchors in config files (#412)
- New `timeout` option on `Client.fetch()`:
  ```python
  client.fetch(url, timeout=10)
  ```

### Changed

- **Breaking:** `Config.load()` now raises `ConfigError` instead of `ValueError`
- Default log level is now `INFO` (was `DEBUG`)

### Fixed

- Crash when the config path contained spaces (#398)
- `deploy` ignored `--region` when `--profile` was also set (#405)

### Deprecated

- `Client.get_raw()`; use `Client.fetch(raw=True)` instead

## [2.3.1] - 2026-09-28

### Fixed

- Memory leak in the retry loop under sustained 5xx responses

## [2.3.0] - 2026-09-10

### Added

- Windows support
- `status` command shows the active profile

### Removed

- Python 3.9 support

[2.4.0]: https://example.com/compare/v2.3.1...v2.4.0
[2.3.1]: https://example.com/compare/v2.3.0...v2.3.1
[2.3.0]: https://example.com/compare/v2.2.0...v2.3.0
