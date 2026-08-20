#!/usr/bin/env python3
"""Regenerate the manual community-driver approval workflow choices.

GitHub workflow_dispatch choice lists are static and finite. Keep the friendly
menus below GitHub's practical option ceiling; the exact candidateKey fallback
remains available for anything not shown in a dropdown.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "community" / "candidates.json"
APPROVED = ROOT / "community" / "community-drivers.json"
WORKFLOW = ROOT / ".github" / "workflows" / "manage-community-driver-approval.yml"
MAX_DROPDOWN_CHOICES = 95


def candidate_label(candidate: dict) -> str:
    base = (
        candidate.get("displayName")
        or " / ".join(candidate.get("models") or [])
        or candidate.get("path")
        or candidate.get("candidateKey")
        or "Community driver"
    )
    digest = hashlib.sha256(str(candidate.get("candidateKey") or base).encode("utf-8")).hexdigest()[:6]
    return f"{base} [{digest}]"


def yaml_single_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def option_block(labels: list[str], empty_label: str) -> tuple[str, int]:
    total = len(labels)
    if not labels:
        labels = [empty_label]
    elif total > MAX_DROPDOWN_CHOICES:
        labels = labels[:MAX_DROPDOWN_CHOICES]
    return "\n".join(f"          - {yaml_single_quote(label)}" for label in labels), total


def main() -> None:
    candidate_payload = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    approved_payload = json.loads(APPROVED.read_text(encoding="utf-8"))

    candidates = list(candidate_payload.get("candidates", []))
    approved = list(approved_payload.get("drivers", []))
    approved_keys = {str(d.get("candidateKey") or "") for d in approved}

    new_candidates = [
        c for c in candidates
        if c.get("candidateKey") and str(c.get("candidateKey")) not in approved_keys
    ]
    new_labels = [candidate_label(c) for c in new_candidates]
    approved_labels = [candidate_label(c) for c in approved if c.get("candidateKey")]

    new_options, new_total = option_block(new_labels, "No new candidates to approve")
    approved_options, approved_total = option_block(approved_labels, "No approved drivers to remove")

    workflow = f"""name: Manage Community Driver Approval

on:
  workflow_dispatch:
    inputs:
      action:
        description: 'Approve a new candidate or remove an approval'
        required: true
        default: approve
        type: choice
        options:
          - approve
          - remove
      new_driver_choice:
        description: 'NEW candidate to approve (first {MAX_DROPDOWN_CHOICES}; use key fallback if needed)'
        required: false
        type: choice
        options:
{new_options}
      approved_driver_choice:
        description: 'APPROVED driver to remove (first {MAX_DROPDOWN_CHOICES}; use key fallback if needed)'
        required: false
        type: choice
        options:
{approved_options}
      manual_candidate_key:
        description: 'Optional exact candidateKey override/fallback'
        required: false
        type: string
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
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Manage approval
        env:
          ACTION_NAME: ${{{{ inputs.action }}}}
          NEW_DRIVER_CHOICE: ${{{{ inputs.new_driver_choice }}}}
          APPROVED_DRIVER_CHOICE: ${{{{ inputs.approved_driver_choice }}}}
          MANUAL_CANDIDATE_KEY: ${{{{ inputs.manual_candidate_key }}}}
          APPROVAL_NOTE: ${{{{ inputs.approval_note }}}}
        run: |
          python - <<'PY'
          import os, subprocess, sys
          action = os.environ['ACTION_NAME'].strip()
          cmd = [sys.executable, 'scripts/manage_community_approvals.py', action]
          manual = os.environ.get('MANUAL_CANDIDATE_KEY', '').strip()
          if manual:
              cmd.append(manual)
          else:
              choice = (os.environ.get('NEW_DRIVER_CHOICE', '') if action == 'approve' else os.environ.get('APPROVED_DRIVER_CHOICE', '')).strip()
              if not choice or choice.startswith('No new candidates') or choice.startswith('No approved drivers'):
                  raise SystemExit('Choose a driver or provide manual_candidate_key.')
              cmd += ['--label', choice]
          note = os.environ.get('APPROVAL_NOTE', '').strip()
          if note:
              cmd += ['--note', note]
          subprocess.check_call(cmd)
          PY

      - name: Refresh approval dropdown choices
        run: python scripts/generate_approval_workflow.py

      - name: Commit approval changes
        run: |
          if git diff --quiet -- community/community-drivers.json .github/workflows/manage-community-driver-approval.yml; then
            echo "No approval catalog changes."
            exit 0
          fi
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add community/community-drivers.json .github/workflows/manage-community-driver-approval.yml
          git commit -m "${{{{ inputs.action }}}} community driver approval"
          git push
"""

    WORKFLOW.write_text(workflow, encoding="utf-8")
    print(f"New candidates: {new_total}; dropdown shows {min(new_total, MAX_DROPDOWN_CHOICES)}")
    print(f"Approved drivers: {approved_total}; removal dropdown shows {min(approved_total, MAX_DROPDOWN_CHOICES)}")
    if new_total > MAX_DROPDOWN_CHOICES or approved_total > MAX_DROPDOWN_CHOICES:
        print("Dropdown truncated safely; manual_candidate_key remains available for hidden entries.")


if __name__ == "__main__":
    main()
