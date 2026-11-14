import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _pyproject_version() -> str:
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


def test_uv_lock_matches_pyproject_version():
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    match = re.search(
        r'^name = "market-data-hub"\nversion = "([^"]+)"', lock, re.MULTILINE
    )
    assert match, "market-data-hub entry not found in uv.lock"
    assert match.group(1) == _pyproject_version()


def test_admin_package_versions_match_pyproject_version():
    expected = _pyproject_version()
    package = json.loads((ROOT / "admin/package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "admin/package-lock.json").read_text(encoding="utf-8"))

    assert package["version"] == expected
    assert lock["version"] == expected
    assert lock["packages"][""]["version"] == expected
