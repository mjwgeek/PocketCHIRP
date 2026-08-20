#!/usr/bin/env python3
"""Discover likely community CHIRP drivers without auto-publishing them."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "community" / "sources.json"
OUT = ROOT / "community" / "candidates.json"
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
API = "https://api.github.com"
UA = "PocketCHIRP-Community-Driver-Discovery/3"


def api_json(path_or_url: str):
    url = path_or_url if path_or_url.startswith("http") else API + path_or_url
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", UA)
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise


def raw_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if TOKEN and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def looks_like_driver(text: str, hints: list[str]) -> tuple[bool, list[str]]:
    found = [hint for hint in hints if hint in text]
    structural = (
        "chirp" in text.lower()
        and ("CloneModeRadio" in text or "LiveRadio" in text)
        and ("directory.register" in text or "@directory.register" in text)
    )
    return structural or len(found) >= 3, found


def extract_models(text: str):
    vendors = re.findall(r'^\s*VENDOR\s*=\s*[\"\']([^\"\']+)', text, re.M)
    models = re.findall(r'^\s*MODEL\s*=\s*[\"\']([^\"\']+)', text, re.M)
    variants = re.findall(r'^\s*VARIANT\s*=\s*[\"\']([^\"\']+)', text, re.M)
    return {
        "vendors": sorted(set(vendors))[:20],
        "models": sorted(set(models))[:40],
        "variants": sorted(set(variants))[:20],
    }


def add_candidate(store: dict, candidate: dict):
    key = candidate["candidateKey"]
    existing = store.get(key)
    if not existing:
        store[key] = candidate
        return
    reasons = set(existing.get("reasons", [])) | set(candidate.get("reasons", []))
    existing["reasons"] = sorted(reasons)
    if len(candidate.get("models", [])) > len(existing.get("models", [])):
        existing.update(candidate)
        existing["reasons"] = sorted(reasons)


def inspect_repo_python(repo_full_name: str, default_branch: str, hints: list[str], store: dict,
                        reason: str, scan_all_python: bool = False):
    tree = api_json(f"/repos/{repo_full_name}/git/trees/{urllib.parse.quote(default_branch, safe='')}?recursive=1")
    items = tree.get("tree", [])

    paths = [str(item.get("path") or "").lower() for item in items if item.get("type") == "blob"]
    bundled_driver_count = sum(1 for p in paths if "/chirp/drivers/" in "/" + p and p.endswith(".py"))
    has_chirp_core = any(p.endswith("chirp/chirp_common.py") for p in paths)
    if has_chirp_core and bundled_driver_count >= 30:
        print(f"skip bundled CHIRP copy: {repo_full_name} ({bundled_driver_count} driver files)")
        return

    for item in items:
        path = item.get("path", "")
        if item.get("type") != "blob" or not path.endswith(".py"):
            continue
        pl = path.lower()
        if not scan_all_python and not (
            "driver" in pl or pl.startswith("drivers/") or pl.startswith("chirp/drivers/")
        ):
            continue
        if any(part in pl for part in ("/test", "tests/", "__pycache__", ".venv/", "venv/")):
            continue
        if int(item.get("size") or 0) > 750_000:
            continue
        raw_url = f"https://raw.githubusercontent.com/{repo_full_name}/{default_branch}/{urllib.parse.quote(path)}"
        try:
            data = raw_bytes(raw_url)
            text = data.decode("utf-8", errors="replace")
        except Exception:
            continue
        ok, found_hints = looks_like_driver(text, hints)
        if not ok:
            continue
        meta = extract_models(text)
        if not meta["models"]:
            continue
        sha = hashlib.sha256(data).hexdigest()
        key = f"repo:{repo_full_name}:{path}"
        add_candidate(store, {
            "candidateKey": key,
            "type": "repository-file",
            "repository": repo_full_name,
            "path": path,
            "sourceUrl": f"https://github.com/{repo_full_name}/blob/{default_branch}/{path}",
            "downloadUrl": raw_url,
            "sha256": sha,
            "vendors": meta["vendors"],
            "models": meta["models"],
            "variants": meta["variants"],
            "hintsMatched": found_hints,
            "reasons": [reason],
            "status": "needs-review",
        })


def repo_meta(repo_full_name: str):
    return api_json(f"/repos/{repo_full_name}")


def discover_explicit_repositories(cfg: dict, store: dict, scanned: set[str]):
    hints = cfg.get("codeSearchHints") or []
    ignored = set(cfg.get("ignoredRepositories") or [])
    for source in cfg.get("explicitRepositories") or []:
        full = source.get("repo")
        if not full or full in ignored or full in scanned:
            continue
        try:
            meta = repo_meta(full)
            if meta.get("archived"):
                continue
            inspect_repo_python(
                full,
                meta.get("default_branch") or "main",
                hints,
                store,
                "explicit repository source",
                bool(source.get("scanAllPython")),
            )
            scanned.add(full)
        except Exception as exc:
            print(f"warning: explicit repo inspection failed for {full}: {exc}", file=sys.stderr)


def discover_owned_repositories(cfg: dict, store: dict, scanned: set[str]):
    owner_cfg = cfg.get("ownedRepositoryScan") or {}
    owner = owner_cfg.get("owner")
    if not owner:
        return
    hints = cfg.get("codeSearchHints") or []
    keywords = [str(x).lower() for x in owner_cfg.get("nameKeywords") or []]
    ignored = set(owner_cfg.get("ignoredRepositories") or []) | set(cfg.get("ignoredRepositories") or [])
    page = 1
    while page <= 5:
        repos = api_json(f"/users/{urllib.parse.quote(owner)}/repos?per_page=100&page={page}&sort=updated")
        if not repos:
            break
        for repo in repos:
            full = repo.get("full_name")
            name = (repo.get("name") or "").lower()
            desc = (repo.get("description") or "").lower()
            if not full or full in ignored or full in scanned or repo.get("archived"):
                continue
            if keywords and not any(k in name or k in desc for k in keywords):
                continue
            try:
                inspect_repo_python(
                    full,
                    repo.get("default_branch") or "main",
                    hints,
                    store,
                    f"owned repository scan: {owner}",
                    bool(owner_cfg.get("scanAllPython")),
                )
                scanned.add(full)
            except Exception as exc:
                print(f"warning: owned repo inspection failed for {full}: {exc}", file=sys.stderr)
        if len(repos) < 100:
            break
        page += 1


def discover_repositories(cfg: dict, store: dict, scanned: set[str]):
    hints = cfg.get("codeSearchHints") or []
    ignored = set(cfg.get("ignoredRepositories") or [])
    for query in cfg.get("repositorySearches") or []:
        focused = any(k in query.lower() for k in ("quansheng", "uv-k", "uvk5", "uvk6", "f4hwn"))
        q = urllib.parse.quote(query)
        result = api_json(f"/search/repositories?q={q}&sort=updated&order=desc&per_page=30")
        for repo in result.get("items", []):
            full = repo.get("full_name")
            if not full or full in ignored or full in scanned or repo.get("archived"):
                continue
            default_branch = repo.get("default_branch") or "main"
            try:
                inspect_repo_python(
                    full,
                    default_branch,
                    hints,
                    store,
                    f"repository search: {query}",
                    focused,
                )
                scanned.add(full)
            except Exception as exc:
                print(f"warning: repo inspection failed for {full}: {exc}", file=sys.stderr)


def discover_pull_requests(cfg: dict, store: dict):
    hints = cfg.get("codeSearchHints") or []
    ignored_prs = set(cfg.get("ignoredPullRequests") or [])
    for source in cfg.get("repositories") or []:
        if not source.get("watchOpenPullRequests"):
            continue
        repo = source["repo"]
        prs = api_json(f"/repos/{repo}/pulls?state=open&sort=updated&direction=desc&per_page=100")
        for pr in prs:
            prn = pr.get("number")
            if f"{repo}#{prn}" in ignored_prs:
                continue
            title = pr.get("title") or ""
            files = api_json(f"/repos/{repo}/pulls/{prn}/files?per_page=100")
            for f in files:
                path = f.get("filename") or ""
                if not path.startswith("chirp/drivers/") or not path.endswith(".py"):
                    continue
                if path.endswith("/fake.py") or path.endswith("/generic_xml.py"):
                    continue
                raw_url = f.get("raw_url")
                if not raw_url:
                    continue
                try:
                    data = raw_bytes(raw_url)
                    text = data.decode("utf-8", errors="replace")
                except Exception:
                    continue
                ok, found_hints = looks_like_driver(text, hints)
                if not ok:
                    continue
                meta = extract_models(text)
                if not meta["models"]:
                    continue
                sha = hashlib.sha256(data).hexdigest()
                key = f"pr:{repo}#{prn}:{path}"
                add_candidate(store, {
                    "candidateKey": key,
                    "type": "pull-request-file",
                    "repository": repo,
                    "pullRequest": prn,
                    "pullRequestTitle": title,
                    "path": path,
                    "sourceUrl": pr.get("html_url"),
                    "downloadUrl": raw_url,
                    "sha256": sha,
                    "vendors": meta["vendors"],
                    "models": meta["models"],
                    "variants": meta["variants"],
                    "hintsMatched": found_hints,
                    "reasons": ["open pull request in watched repository"],
                    "status": "needs-review",
                })


def dedupe_exact_files(candidates: list[dict]) -> list[dict]:
    """Collapse exact byte-identical forks/copies while retaining source history."""
    by_sha: dict[str, list[dict]] = {}
    for candidate in candidates:
        by_sha.setdefault(candidate.get("sha256") or candidate["candidateKey"], []).append(candidate)

    out = []
    preferred_sources = ("mjwgeek/", "egzumer/", "armel/", "kk7ds/")
    for group in by_sha.values():
        if len(group) == 1:
            out.append(group[0])
            continue

        def rank(item):
            repo = item.get("repository", "")
            source_rank = next((i for i, p in enumerate(preferred_sources) if repo.startswith(p)), 99)
            type_rank = 0 if item.get("type") == "pull-request-file" else 1
            return (source_rank, type_rank, repo.lower(), item.get("path", "").lower())

        group.sort(key=rank)
        keep = group[0]
        keep["duplicateSources"] = [
            {
                "repository": x.get("repository"),
                "path": x.get("path"),
                "sourceUrl": x.get("sourceUrl"),
            }
            for x in group[1:]
        ]
        reasons = set(keep.get("reasons", []))
        reasons.add(f"collapsed {len(group) - 1} byte-identical duplicate source(s)")
        keep["reasons"] = sorted(reasons)
        out.append(keep)
    return out


def main():
    cfg = json.loads(SOURCES.read_text(encoding="utf-8"))
    found = {}
    scanned: set[str] = set()
    discover_pull_requests(cfg, found)
    discover_explicit_repositories(cfg, found, scanned)
    discover_owned_repositories(cfg, found, scanned)
    discover_repositories(cfg, found, scanned)
    candidates = dedupe_exact_files(list(found.values()))
    candidates.sort(key=lambda x: (
        x.get("repository", "").lower(),
        x.get("path", "").lower(),
        x.get("candidateKey", ""),
    ))
    payload = {
        "schemaVersion": 2,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "candidateCount": len(candidates),
        "candidates": candidates,
    }
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(candidates)} candidate(s) to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
