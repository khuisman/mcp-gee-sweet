"""CI's Python matrix must match the versions pyproject.toml claims to support.

#618 tied the matrix to the classifiers, but nothing checked it, so 3.14 and 3.15
were added to neither list for a year (#1212).
"""

import re
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_CLASSIFIER = re.compile(r"Programming Language :: Python :: (3\.\d+)$")


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _pyproject():
    with open(_REPO_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


def _classifier_versions() -> list[str]:
    classifiers = _pyproject()["project"]["classifiers"]
    return sorted(
        (m.group(1) for c in classifiers if (m := _CLASSIFIER.match(c))), key=_version_key
    )


def _ci_matrix_versions() -> list[str]:
    ci = (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    match = re.search(r"^\s*python-version:\s*\[([^\]]*)\]", ci, re.MULTILINE)
    assert match, "ci.yml has no inline python-version matrix list"
    return sorted(re.findall(r'"(3\.\d+)"', match.group(1)), key=_version_key)


def test_ci_matrix_matches_classifiers():
    assert _ci_matrix_versions() == _classifier_versions()


def test_lowest_classifier_matches_requires_python():
    requires_python = _pyproject()["project"]["requires-python"]
    assert requires_python == f">={_classifier_versions()[0]}"
