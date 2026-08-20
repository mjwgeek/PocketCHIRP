#!/usr/bin/env python3
"""Approve or remove PocketCHIRP community driver catalog entries.

This script never discovers drivers. It only moves exact, already-discovered
candidate records into or out of community/community-drivers.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "community" / "candidates.json"
APPROVED = ROOT / "community" / "community-drivers.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def stable_id(candidate: dict) -> str:
    base = candidate.get("displayName") or "-".join(candidate.get("models") or []) or candidate.get("path") or "community-driver"
    slug = re.sub(r"[^a-z0-9]+", "-", str(base).lower()).strip("-")[:72] or "community-driver"
    digest = hashlib.sha256(str(candidate.get("candidateKey") or base).encode("utf-8")).hexdigest()[:10]
    return f"{slug}-{digest}"


def validate_candidate(candidate: dict) -> None:
    required = ("candidateKey", "downloadUrl", "sha256")
    missing = [k for k in required if not str(candidate.get(k) or "").strip()]
    if missing:
        raise SystemExit(f"Candidate is missing required field(s): {', '.join(missing)}")
    sha = str(candidate["sha256"]).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise SystemExit("Candidate SHA-256 is not a valid 64-character hex digest")
    url = str(candidate["downloadUrl"])
    if not url.startswith("https://raw.githubusercontent.com/"):
        raise SystemExit("Candidate downloadUrl must use https://raw.githubusercontent.com/")


def approved_entry(candidate: dict, note: str = "") -> dict:
    validate_candidate(candidate)
    entry = dict(candidate)
    entry["id"] = stable_id(candidate)
    entry["status"] = "approved"
    entry["approved"] = True
    entry["approvedAt"] = now_iso()
    if note.strip():
        entry["approvalNote"] = note.strip()
    return entry


def find_candidate(payload: dict, key: str) -> dict | None:
    key = key.strip()
    for candidate in payload.get("candidates", []):
        if candidate.get("candidateKey") == key:
            return candidate
    return None


def split_keys(raw_values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in raw_values:
        for part in re.split(r"[\n,]+", raw):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("approve", "remove", "list"))
    parser.add_argument("keys", nargs="*", help="candidateKey(s), comma/newline separated values also accepted")
    parser.add_argument("--note", default="", help="optional approval note")
    args = parser.parse_args()

    candidates_payload = load_json(CANDIDATES)
    approved_payload = load_json(APPROVED)
    approved_payload.setdefault("schemaVersion", 1)
    approved_payload.setdefault("catalogRevision", 0)
    approved_payload.setdefault("drivers", [])
    approved_payload.setdefault("policy", {
        "autoPublishCandidates": False,
        "requireManualApproval": True,
        "verifySha256BeforeInstall": True,
    })

    if args.action == "list":
        approved_keys = {d.get("candidateKey") for d in approved_payload.get("drivers", [])}
        for candidate in candidates_payload.get("candidates", []):
            marker = "APPROVED" if candidate.get("candidateKey") in approved_keys else "review"
            print(f"[{marker}] {candidate.get('candidateKey')} :: {candidate.get('displayName') or ', '.join(candidate.get('models', []))}")
        return

    keys = split_keys(args.keys)
    if not keys:
        raise SystemExit("At least one candidateKey is required")

    drivers = list(approved_payload.get("drivers", []))
    changed = False

    if args.action == "approve":
        by_key = {d.get("candidateKey"): i for i, d in enumerate(drivers)}
        for key in keys:
            candidate = find_candidate(candidates_payload, key)
            if candidate is None:
                raise SystemExit(f"Candidate not found: {key}")
            entry = approved_entry(candidate, args.note)
            if key in by_key:
                old = drivers[by_key[key]]
                # Keep original approval timestamp if the reviewed bytes did not change.
                if old.get("sha256") == entry.get("sha256") and old.get("approvedAt"):
                    entry["approvedAt"] = old["approvedAt"]
                drivers[by_key[key]] = entry
                print(f"Refreshed approval: {key}")
            else:
                drivers.append(entry)
                by_key[key] = len(drivers) - 1
                print(f"Approved: {key}")
            changed = True

    elif args.action == "remove":
        wanted = set(keys)
        before = len(drivers)
        drivers = [d for d in drivers if d.get("candidateKey") not in wanted and d.get("id") not in wanted]
        removed = before - len(drivers)
        if removed == 0:
            raise SystemExit("No approved entries matched the supplied key(s)")
        print(f"Removed {removed} approval(s)")
        changed = True

    if changed:
        drivers.sort(key=lambda d: (
            str((d.get("vendors") or [""])[0]).lower(),
            str((d.get("models") or [""])[0]).lower(),
            str(d.get("version") or ""),
            str(d.get("candidateKey") or ""),
        ))
        approved_payload["drivers"] = drivers
        approved_payload["catalogRevision"] = int(approved_payload.get("catalogRevision") or 0) + 1
        approved_payload["updated"] = today()
        approved_payload["approvedCount"] = len(drivers)
        save_json(APPROVED, approved_payload)
        print(f"Catalog now contains {len(drivers)} approved driver(s); revision {approved_payload['catalogRevision']}")


if __name__ == "__main__":
    main()
