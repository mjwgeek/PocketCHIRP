#!/usr/bin/env python3
"""Regenerate the manual community-driver approval workflow choices.

GitHub Actions workflow_dispatch choice inputs are static YAML. This script
rebuilds the friendly driver dropdown from community/candidates.json after each
discovery run so maintainers do not need to copy candidateKey values by hand.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "community" / "candidates.json"
WORKFLOW = ROOT / ".github" / "workflows" / "manage-community-driver-approval.yml"


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


def main() -> None:
    payload = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    candidates = list(payload.get("candidates", []))

    labels = [candidate_label(c) for c in candidates if c.get("candidateKey")]
    if not labels:
        labels = ["No candidates discovered yet"]

    option_lines = "\n".join(f"          - {yaml_single_quote(label)}" for label in labels)

    workflow = f"""name: Manage Community Driver Approval

on:
  workflow_dispatch:
    inputs:
      action:
        description: 'Approve or remove approval'
        required: true
        default: approve
        type: choice
        options:
          - approve
          - remove
      driver_choice:
        description: 'Community driver / firmware version'
        required: true
        type: choice
        options:
{option_lines}
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
        uses: actions/checkout@v7

      - name: Set up Python
        uses: actions/setup-python@v7
        with:
          python-version: '3.12'

      - name: Manage approval
        env:
          ACTION_NAME: ${{{{ inputs.action }}}}
          DRIVER_CHOICE: ${{{{ inputs.driver_choice }}}}
          MANUAL_CANDIDATE_KEY: ${{{{ inputs.manual_candidate_key }}}}
          APPROVAL_NOTE: ${{{{ inputs.approval_note }}}}
        run: |
          python - <<'PY'
          import os
          import subprocess
          import sys

          cmd = [sys.executable, 'scripts/manage_community_approvals.py', os.environ['ACTION_NAME']]
          manual = os.environ.get('MANUAL_CANDIDATE_KEY', '').strip()
          choice = os.environ.get('DRIVER_CHOICE', '').strip()
          if manual:
              cmd.append(manual)
          elif choice:
              cmd += ['--label', choice]
          else:
              raise SystemExit('Choose a community driver or provide manual_candidate_key')

          note = os.environ.get('APPROVAL_NOTE', '').strip()
          if note:
              cmd += ['--note', note]
          subprocess.check_call(cmd)
          PY

      - name: Show resulting catalog
        run: |
          python - <<'PY'
          import json
          from pathlib import Path
          data = json.loads(Path('community/community-drivers.json').read_text())
          print(f\"Catalog revision: {{data.get('catalogRevision')}}\")
          print(f\"Approved drivers: {{len(data.get('drivers', []))}}\")
          for driver in data.get('drivers', []):
              print(f\"- {{driver.get('displayName') or driver.get('candidateKey')}}\")
          PY

      - name: Commit approval changes
        run: |
          if git diff --quiet -- community/community-drivers.json; then
            echo \"No approval catalog changes.\"
            exit 0
          fi
          git config user.name \"github-actions[bot]\"
          git config user.email \"41898282+github-actions[bot]@users.noreply.github.com\"
          git add community/community-drivers.json
          git commit -m \"${{{{ inputs.action }}}} community driver approval\"
          git push
"""

    WORKFLOW.write_text(workflow, encoding="utf-8")
    print(f"Wrote {len(labels)} friendly approval choice(s) to {WORKFLOW.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
