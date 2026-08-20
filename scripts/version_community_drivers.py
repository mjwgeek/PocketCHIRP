#!/usr/bin/env python3
"""Annotate discovered CHIRP driver candidates with version/family metadata.

This deliberately preserves historical drivers. Older firmware-specific drivers
may be required by radios that have intentionally stayed on an older firmware.
The annotations let PocketCHIRP present a current/recommended entry first while
still showing every discovered version explicitly.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "community" / "candidates.json"

VERSION_PATTERNS = [
    re.compile(r"(?:^|[_\-])ver[_\-]?(\d+(?:[_.]\d+){1,3})(?:[_\-.]|$)", re.I),
    re.compile(r"(?:^|[_\-])v(\d+(?:[_.]\d+){1,3})(?:[_\-.]|$)", re.I),
    re.compile(r"(?:^|[_\-])(\d+[_.]\d+[_.]\d+)(?:[_\-.]|$)", re.I),
    re.compile(r"(?:^|[_\-])(\d+[_.]\d+)(?:[_\-.]|$)", re.I),
]

HISTORICAL_PATH_MARKERS = (
    "archive/", "/archive/", "archived/", "/archived/",
    "old/", "/old/", "older/", "/older/", "legacy/", "/legacy/",
    "previous/", "/previous/", "стар",  # catches common Russian old-version folders
)


def normalize_version(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip().replace("_", ".")
    value = re.sub(r"\.+", ".", value).strip(".")
    return value or None


def infer_version(candidate: dict) -> str | None:
    haystacks = [
        candidate.get("path", ""),
        " ".join(candidate.get("models") or []),
        " ".join(candidate.get("variants") or []),
        candidate.get("pullRequestTitle", ""),
    ]
    for text in haystacks:
        for pattern in VERSION_PATTERNS:
            match = pattern.search(text or "")
            if match:
                return normalize_version(match.group(1))
    return None


def version_key(value: str | None):
    if not value:
        return (-1,)
    nums = [int(x) for x in re.findall(r"\d+", value)]
    return tuple(nums) if nums else (-1,)


def is_historical_path(path: str) -> bool:
    pl = (path or "").lower().replace("\\", "/")
    return any(marker in pl for marker in HISTORICAL_PATH_MARKERS)


def family_key(candidate: dict) -> str:
    repo = candidate.get("repository", "").lower()
    models = [str(x).strip().lower() for x in candidate.get("models") or []]
    vendors = [str(x).strip().lower() for x in candidate.get("vendors") or []]
    path = Path(candidate.get("path") or "driver.py").name.lower()
    stem = path[:-3] if path.endswith(".py") else path

    # Remove release/version/language suffixes so revisions group together.
    stem = re.sub(r"(?:_ver)?[_\-]?v?\d+(?:[_\-.]\d+){1,3}", "", stem, flags=re.I)
    stem = re.sub(r"(?:_fr|_en|_de|_es|_it|_pt|_pl|_ru|_k)$", "", stem, flags=re.I)
    stem = re.sub(r"[_\-.]+", "_", stem).strip("_")

    # Model strings are normally more stable than filenames, but include repo
    # so unrelated projects with the same model label do not collapse together.
    model_part = "|".join(sorted(set(models))) or stem
    vendor_part = "|".join(sorted(set(vendors)))
    return f"{repo}::{vendor_part}::{model_part}::{stem}"


def display_name(candidate: dict) -> str:
    vendor = ", ".join(candidate.get("vendors") or []) or "Community"
    models = ", ".join(candidate.get("models") or []) or Path(candidate.get("path") or "driver.py").stem
    version = candidate.get("version")
    suffix = f" v{version}" if version else ""
    if candidate.get("languageVariant"):
        suffix += f" ({candidate['languageVariant']})"
    return f"{vendor} {models}{suffix}".strip()


def annotate(rows: list[dict]) -> None:
    families: dict[str, list[dict]] = {}

    for row in rows:
        version = infer_version(row)
        row["version"] = version
        path = row.get("path", "")
        row["historical"] = is_historical_path(path)
        row["releaseTier"] = "historical" if row["historical"] else "current"

        filename = Path(path or "").name.lower()
        if re.search(r"(?:^|_)fr(?:_|\.|$)", filename):
            row["languageVariant"] = "FR"
        elif re.search(r"(?:^|_)en(?:_|\.|$)", filename):
            row["languageVariant"] = "EN"

        row["versionFamily"] = family_key(row)
        families.setdefault(row["versionFamily"], []).append(row)

    for members in families.values():
        # Prefer non-historical entries, then highest parsed version. If no
        # version can be parsed, a top-level/current-path entry still wins.
        ranked = sorted(
            members,
            key=lambda x: (
                0 if x.get("historical") else 1,
                version_key(x.get("version")),
                x.get("path", ""),
            ),
            reverse=True,
        )
        winner = ranked[0]
        for row in members:
            row["latestInFamily"] = row is winner
            row["recommended"] = row is winner and not row.get("historical")
            row["displayName"] = display_name(row)
            row["availableVersions"] = sorted(
                {m.get("version") for m in members if m.get("version")},
                key=version_key,
                reverse=True,
            )


def main():
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    rows = payload.get("candidates") or []
    annotate(rows)

    # Current/recommended entries appear first, but historical versions remain
    # in the same catalog and are explicitly version-labelled for the GUI.
    rows.sort(key=lambda x: (
        x.get("versionFamily", ""),
        0 if x.get("recommended") else 1,
        0 if not x.get("historical") else 1,
        tuple(-n for n in version_key(x.get("version"))),
        x.get("path", "").lower(),
    ))

    payload["schemaVersion"] = max(int(payload.get("schemaVersion") or 1), 3)
    payload["versionAware"] = True
    payload["catalogPolicy"] = (
        "All discovered versions are retained. Current/newest entries are highlighted, "
        "while historical firmware-specific drivers remain selectable by version."
    )
    payload["currentCount"] = sum(1 for x in rows if not x.get("historical"))
    payload["historicalCount"] = sum(1 for x in rows if x.get("historical"))
    payload["versionedCount"] = sum(1 for x in rows if x.get("version"))
    payload["candidates"] = rows

    CATALOG.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(
        f"Version metadata: {payload['currentCount']} current, "
        f"{payload['historicalCount']} historical, {payload['versionedCount']} version-labelled"
    )


if __name__ == "__main__":
    main()
