#!/usr/bin/env python3
"""Generate scalable per-vendor community-driver approval workflows.

GitHub workflow_dispatch choice inputs are finite. This generator groups
unapproved candidates and approved drivers by vendor, then splits each group
into pages safely below the choice ceiling. Generated workflows are disposable
and rebuilt from candidates.json/community-drivers.json.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "community" / "candidates.json"
APPROVED = ROOT / "community" / "community-drivers.json"
WORKFLOW_DIR = ROOT / ".github" / "workflows"
PREFIX = "community-driver-"
MAX_CHOICES = 90


def candidate_label(candidate: dict) -> str:
    base = (candidate.get("displayName") or " / ".join(candidate.get("models") or [])
            or candidate.get("path") or candidate.get("candidateKey") or "Community driver")
    digest = hashlib.sha256(str(candidate.get("candidateKey") or base).encode()).hexdigest()[:6]
    return f"{base} [{digest}]"


def vendor_name(row: dict) -> str:
    vendors = [str(v).strip() for v in row.get("vendors") or [] if str(v).strip()]
    if vendors:
        return vendors[0]
    repo = str(row.get("repository") or "")
    if repo == "ijvradio.com":
        return "Quansheng"
    return "Other"


def slug(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return s or "other"


def q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def chunks(rows: list[dict]):
    for i in range(0, len(rows), MAX_CHOICES):
        yield rows[i:i+MAX_CHOICES]


def workflow_text(action: str, vendor: str, page: int, pages: int, rows: list[dict]) -> str:
    labels = [candidate_label(r) for r in rows]
    title_action = "Approve New" if action == "approve" else "Remove Approval"
    page_suffix = f" {page}/{pages}" if pages > 1 else ""
    options = "\n".join(f"          - {q(x)}" for x in labels)
    return f"""name: {title_action} — {vendor}{page_suffix}

on:
  workflow_dispatch:
    inputs:
      driver_choice:
        description: '{title_action}: {vendor}{page_suffix}'
        required: true
        type: choice
        options:
{options}
      approval_note:
        description: 'Optional note about testing/review'
        required: false
        type: string

permissions:
  contents: write

jobs:
  manage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: {title_action}
        env:
          DRIVER_CHOICE: ${{{{ inputs.driver_choice }}}}
          APPROVAL_NOTE: ${{{{ inputs.approval_note }}}}
        run: |
          python - <<'PY'
          import os, subprocess, sys
          cmd=[sys.executable,'scripts/manage_community_approvals.py','{action}','--label',os.environ['DRIVER_CHOICE']]
          note=os.environ.get('APPROVAL_NOTE','').strip()
          if note:
              cmd += ['--note', note]
          subprocess.check_call(cmd)
          PY
      - name: Rebuild approval menus
        run: python scripts/generate_approval_workflow.py
      - name: Commit approval and menus
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add community/community-drivers.json .github/workflows/community-driver-*.yml
          git add -u .github/workflows
          if git diff --cached --quiet; then
            echo "No changes."
            exit 0
          fi
          git commit -m "{action} community driver: {vendor}"
          git push
"""


def main():
    cp=json.loads(CANDIDATES.read_text(encoding='utf-8'))
    ap=json.loads(APPROVED.read_text(encoding='utf-8'))
    candidates=list(cp.get('candidates') or [])
    approved=list(ap.get('drivers') or [])
    approved_keys={str(x.get('candidateKey') or '') for x in approved}
    new=[x for x in candidates if x.get('candidateKey') and str(x.get('candidateKey')) not in approved_keys]

    groups=defaultdict(lambda: {'approve':[], 'remove':[]})
    for row in new:
        groups[vendor_name(row)]['approve'].append(row)
    for row in approved:
        if row.get('candidateKey'):
            groups[vendor_name(row)]['remove'].append(row)

    for data in groups.values():
        for key in ('approve','remove'):
            data[key].sort(key=lambda r: candidate_label(r).lower())

    expected=set()
    for vendor in sorted(groups, key=str.lower):
        for action in ('approve','remove'):
            rows=groups[vendor][action]
            if not rows:
                continue
            pages=(len(rows)+MAX_CHOICES-1)//MAX_CHOICES
            for idx, chunk in enumerate(chunks(rows), start=1):
                filename=f"{PREFIX}{action}-{slug(vendor)}-{idx:02d}.yml"
                expected.add(filename)
                (WORKFLOW_DIR/filename).write_text(workflow_text(action,vendor,idx,pages,chunk),encoding='utf-8')

    for path in WORKFLOW_DIR.glob(f"{PREFIX}*.yml"):
        if path.name not in expected:
            path.unlink()

    print(f"Generated {len(expected)} vendor/page workflow(s).")
    print(f"Unapproved candidates: {len(new)}; approved drivers: {len(approved)}")
    for vendor in sorted(groups, key=str.lower):
        a=len(groups[vendor]['approve']); r=len(groups[vendor]['remove'])
        print(f"- {vendor}: {a} to approve, {r} approved")


if __name__ == '__main__':
    main()
