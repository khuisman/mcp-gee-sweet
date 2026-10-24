"""Guards for security-motivated dependency floors in pyproject.toml.

A floor pin added for an incident must not disappear in a later dependency edit:
pip keeps whatever version an existing environment already has unless the
project's own requirement forces it higher.
"""

from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11 — stdlib tomllib landed in 3.11
    import tomli as tomllib

_REPO_ROOT = Path(__file__).resolve().parent.parent

# eMudhra/emSign CA incident — #1217
_CERTIFI_FLOOR = Version("2026.10.19")


def _load_toml(name):
    with open(_REPO_ROOT / name, "rb") as f:
        return tomllib.load(f)


def _requirement(name):
    reqs = [Requirement(r) for r in _load_toml("pyproject.toml")["project"]["dependencies"]]
    matches = [r for r in reqs if r.name.lower() == name]
    assert len(matches) == 1, f"expected exactly one {name} requirement, found {len(matches)}"
    return matches[0]


class TestCertifiFloor:
    def test_requirement_excludes_pre_incident_versions(self):
        spec = _requirement("certifi").specifier
        # The bundle v0.9.4 shipped, and the last version before the fix.
        for version in ("2026.5.20", "2026.10.18"):
            assert not spec.contains(version), f"certifi {version} still satisfies {spec}"
        assert spec.contains(str(_CERTIFI_FLOOR))

    def test_lock_pins_fixed_version(self):
        packages = _load_toml("uv.lock")["package"]
        certifi = [p for p in packages if p["name"] == "certifi"]
        assert len(certifi) == 1
        assert Version(certifi[0]["version"]) >= _CERTIFI_FLOOR
