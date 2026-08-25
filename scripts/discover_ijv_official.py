#!/usr/bin/env python3
"""Add official IJV CHIRP modules to PocketCHIRP community candidates.

The IJV download page publishes direct Python modules and ZIP bundles. Direct
Python modules keep their official download URL. Python files found inside an
official ZIP are mirrored into this repository so each candidate has a stable,
direct HTTPS download whose SHA-256 matches the extracted driver bytes.

These are optional external sources: a temporary ijvradio.com failure must
NEVER make the main PocketCHIRP community discovery workflow fail.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "community" / "candidates.json"
IJV_MIRROR = ROOT / "community" / "ijv-mirror"
RAW_MIRROR_BASE = "https://raw.githubusercontent.com/mjwgeek/PocketCHIRP/main/community/ijv-mirror"
UA = "Mozilla/5.0 PocketCHIRP-IJV-Discovery/1.2"
MAX_DOWNLOAD = 8 * 1024 * 1024
MAX_MEMBER = 2 * 1024 * 1024

OFFICIAL = [
    {
        "kind": "python",
        "firmware": "4.0",
        "url": "https://www.ijvradio.com/Chirp%20plugin/IJV%20V4.0%20Unified.py",
        "label": "IJV V4.0 Unified",
    },
    {
        "kind": "zip",
        "firmware": "3.60",
        "url": "https://www.ijvradio.com/download/IJV_3.60_Chirp.zip",
        "label": "IJV 3.60 CHIRP bundle",
    },
    {
        "kind": "python",
        "firmware": "5.0",
        "url": "https://www.ijvradio.com/Chirp%20plugin/IJV%20V5.0%20Memory.py",
        "label": "IJV V5.0 Memory",
    },
]


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise RuntimeError(f"Official IJV download too large: {url}")
    return data


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def structural_hints(text: str) -> list[str]:
    checks = [
        ("CloneModeRadio", r"\bCloneModeRadio\b"),
        ("directory.register", r"directory\.register"),
        ("RadioSetting", r"\bRadioSetting\b"),
        ("sync_in", r"\bdef\s+sync_in\b"),
        ("sync_out", r"\bdef\s+sync_out\b"),
    ]
    return [name for name, pattern in checks if re.search(pattern, text)]


def extract_models(text: str) -> list[str]:
    models = []
    for match in re.finditer(r"^\s*MODEL\s*=\s*['\"]([^'\"]+)['\"]", text, re.M):
        value = match.group(1).strip()
        if value and value not in models:
            models.append(value)
    return models


def mirror_zip_member(*, firmware: str, member_name: str, data: bytes) -> tuple[str, str]:
    """Persist one extracted ZIP member and return (display filename, raw URL)."""
    filename = PurePosixPath(member_name).name
    if not filename or not filename.lower().endswith(".py"):
        raise RuntimeError(f"Unsafe/non-Python IJV ZIP member name: {member_name}")

    target_dir = IJV_MIRROR / firmware
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename
    target.write_bytes(data)

    quoted_firmware = urllib.parse.quote(firmware, safe="")
    quoted_filename = urllib.parse.quote(filename, safe="")
    raw_url = f"{RAW_MIRROR_BASE}/{quoted_firmware}/{quoted_filename}"
    return filename, raw_url


def make_candidate(*, url: str, firmware: str, label: str, filename: str,
                   data: bytes, zip_source: str | None = None,
                   download_url: str | None = None) -> dict:
    text = safe_text(data)
    hints = structural_hints(text)
    models = extract_models(text) or [f"UV-K5 V3 / UV-K1 (IJV {firmware})"]
    digest = sha256(data)
    source_tag = zip_source or url
    key = f"official:ijvradio:{firmware}:{filename}:{digest[:12]}"
    return {
        "candidateKey": key,
        "type": "official-site-file",
        "repository": "ijvradio.com",
        "path": filename,
        "sourceUrl": source_tag,
        "downloadUrl": download_url or url,
        "sha256": digest,
        "vendors": ["Quansheng"],
        "models": models,
        "variants": [f"Official IJV firmware {firmware}"],
        "hintsMatched": hints,
        "reasons": ["official IJV download source"],
        "status": "needs-review",
        "historical": firmware == "3.60",
        "releaseTier": "historical" if firmware == "3.60" else "current",
        "displayName": f"Quansheng IJV {firmware} — {label}" + (f" — {filename}" if zip_source else ""),
        "officialSource": True,
        "officialFirmware": firmware,
        "archiveSourceUrl": zip_source or "",
        "archiveMember": filename if zip_source else "",
        "installPackaging": "mirrored-zip-member" if zip_source else "direct-python",
    }


def discover_item(item: dict) -> list[dict]:
    raw = fetch_bytes(item["url"])
    if item["kind"] == "python":
        filename = urllib.parse.unquote(urllib.parse.urlparse(item["url"]).path.rsplit("/", 1)[-1])
        return [make_candidate(
            url=item["url"], firmware=item["firmware"], label=item["label"],
            filename=filename, data=raw,
        )]

    found = []
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        members = [m for m in zf.infolist()
                   if not m.is_dir() and m.filename.lower().endswith(".py")]
        if not members:
            raise RuntimeError("ZIP contains no Python driver files")
        for member in members:
            if member.file_size > MAX_MEMBER:
                print(f"WARNING: skipping oversized IJV ZIP member: {member.filename}")
                continue
            data = zf.read(member)
            filename, raw_url = mirror_zip_member(
                firmware=item["firmware"], member_name=member.filename, data=data,
            )
            found.append(make_candidate(
                url=item["url"], firmware=item["firmware"], label=item["label"],
                filename=filename, data=data, zip_source=item["url"],
                download_url=raw_url,
            ))
    return found


def main() -> None:
    payload = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    existing = list(payload.get("candidates", []))

    # Keep prior successful official-IJV rows unless that particular source can
    # be refreshed successfully. This prevents a transient web outage from
    # deleting previously discovered candidates.
    prior_official = [
        r for r in existing
        if r.get("repository") == "ijvradio.com" and r.get("officialSource")
    ]
    non_ijv = [r for r in existing if r not in prior_official]

    refreshed: list[dict] = []
    successful_firmwares: set[str] = set()
    failures = 0

    for item in OFFICIAL:
        try:
            rows = discover_item(item)
            refreshed.extend(rows)
            successful_firmwares.add(str(item["firmware"]))
            print(f"IJV {item['firmware']}: discovered {len(rows)} file(s)")
        except Exception as exc:
            failures += 1
            print(f"WARNING: official IJV {item['firmware']} discovery failed: {exc}")

    # Retain prior rows for only those firmware sources that failed this run.
    retained = [
        r for r in prior_official
        if str(r.get("officialFirmware") or "") not in successful_firmwares
    ]

    rows = non_ijv + retained + refreshed
    payload["candidates"] = rows
    payload["candidateCount"] = len(rows)
    payload["officialIjvSource"] = True
    payload["officialIjvCandidateCount"] = len(retained) + len(refreshed)
    payload["officialIjvLastRunFailures"] = failures
    CANDIDATES.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(
        f"Official IJV discovery complete: {len(refreshed)} refreshed, "
        f"{len(retained)} retained, {failures} source failure(s)."
    )


if __name__ == "__main__":
    main()
