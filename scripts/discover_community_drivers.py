#!/usr/bin/env python3
"""Discover likely community CHIRP drivers without auto-publishing them."""

from __future__ import annotations

import ast
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
UA = "PocketCHIRP-Community-Driver-Discovery/4"


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


def _literal_string(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def extract_models(text: str):
    """Extract metadata while preserving the VENDOR/MODEL relationship.

    CHIRP modules may register radios from multiple manufacturers in one file
    (for example tdh8.py contains TIDRADIO, TID and Radtel classes).  The old
    implementation collected VENDOR and MODEL assignments independently, which
    lost that relationship and allowed the UI/catalog to pair the wrong vendor
    with a model.
    """
    pairs = []
    variants = []
    try:
        tree = ast.parse(text)
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            vendor = model = variant = None
            for stmt in cls.body:
                if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                    continue
                value = _literal_string(stmt.value)
                if value is None:
                    continue
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                for target in targets:
                    if not isinstance(target, ast.Name):
                        continue
                    if target.id == "VENDOR":
                        vendor = value
                    elif target.id == "MODEL":
                        model = value
                    elif target.id == "VARIANT":
                        variant = value
            if model:
                pairs.append({"vendor": vendor or "", "model": model,
                              **({"variant": variant} if variant else {})})
            if variant:
                variants.append(variant)
    except SyntaxError:
        pass

    # Keep legacy aggregate fields for compatibility, but derive them from the
    # paired records whenever possible. Fall back to regex for unusual drivers.
    if pairs:
        vendors = [p["vendor"] for p in pairs if p["vendor"]]
        models = [p["model"] for p in pairs]
    else:
        vendors = re.findall(r'^\s*VENDOR\s*=\s*[\"\']([^\"\']+)', text, re.M)
        models = re.findall(r'^\s*MODEL\s*=\s*[\"\']([^\"\']+)', text, re.M)
        variants = re.findall(r'^\s*VARIANT\s*=\s*[\"\']([^\"\']+)', text, re.M)

    unique_pairs = []
    seen = set()
    for pair in pairs:
        key = (pair.get("vendor", ""), pair.get("model", ""), pair.get("variant", ""))
        if key not in seen:
            seen.add(key)
            unique_pairs.append(pair)

    return {
        "vendors": sorted(set(vendors))[:20],
        "models": sorted(set(models))[:40],
        "variants": sorted(set(variants))[:20],
        "modelEntries": unique_pairs[:60],
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


def candidate_metadata(meta: dict) -> dict:
    return {
        "vendors": meta["vendors"],
        "models": meta["models"],
        "variants": meta["variants"],
        "modelEntries": meta.get("modelEntries", []),
    }


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
        if not scan_all_python and not ("driver" in pl or pl.startswith("drivers/") or pl.startswith("chirp/drivers/")):
            continue
        if any(part in pl for part in ("/test", "tests/", "__pycache__", ".venv/", "venv/")):
            continue
        if int(item.get("size") or 0) > 750_000:
            continue
        raw_url = f"https://raw.githubusercontent.com/{repo_full_name}/{default_branch}/{urllib.parse.quote(path)}"
        try:
            data = raw_bytes(raw_url); text = data.decode("utf-8", errors="replace")
        except Exception:
            continue
        ok, found_hints = looks_like_driver(text, hints)
        if not ok:
            continue
        meta = extract_models(text)
        if not meta["models"]:
            continue
        add_candidate(store, {"candidateKey": f"repo:{repo_full_name}:{path}", "type": "repository-file",
            "repository": repo_full_name, "path": path,
            "sourceUrl": f"https://github.com/{repo_full_name}/blob/{default_branch}/{path}",
            "downloadUrl": raw_url, "sha256": hashlib.sha256(data).hexdigest(), **candidate_metadata(meta),
            "hintsMatched": found_hints, "reasons": [reason], "status": "needs-review"})


def repo_meta(repo_full_name: str):
    return api_json(f"/repos/{repo_full_name}")


def discover_explicit_repositories(cfg: dict, store: dict, scanned: set[str]):
    hints = cfg.get("codeSearchHints") or []; ignored = set(cfg.get("ignoredRepositories") or [])
    for source in cfg.get("explicitRepositories") or []:
        full = source.get("repo")
        if not full or full in ignored or full in scanned: continue
        try:
            meta = repo_meta(full)
            if meta.get("archived"): continue
            inspect_repo_python(full, meta.get("default_branch") or "main", hints, store,
                                "explicit repository source", bool(source.get("scanAllPython")))
            scanned.add(full)
        except Exception as exc:
            print(f"warning: explicit repo inspection failed for {full}: {exc}", file=sys.stderr)


def discover_owned_repositories(cfg: dict, store: dict, scanned: set[str]):
    owner_cfg = cfg.get("ownedRepositoryScan") or {}; owner = owner_cfg.get("owner")
    if not owner: return
    hints = cfg.get("codeSearchHints") or []; keywords = [str(x).lower() for x in owner_cfg.get("nameKeywords") or []]
    ignored = set(owner_cfg.get("ignoredRepositories") or []) | set(cfg.get("ignoredRepositories") or [])
    page = 1
    while page <= 5:
        repos = api_json(f"/users/{urllib.parse.quote(owner)}/repos?per_page=100&page={page}&sort=updated")
        if not repos: break
        for repo in repos:
            full = repo.get("full_name"); name = (repo.get("name") or "").lower(); desc = (repo.get("description") or "").lower()
            if not full or full in ignored or full in scanned or repo.get("archived"): continue
            if keywords and not any(k in name or k in desc for k in keywords): continue
            try:
                inspect_repo_python(full, repo.get("default_branch") or "main", hints, store,
                                    f"owned repository scan: {owner}", bool(owner_cfg.get("scanAllPython")))
                scanned.add(full)
            except Exception as exc:
                print(f"warning: owned repo inspection failed for {full}: {exc}", file=sys.stderr)
        if len(repos) < 100: break
        page += 1


def discover_repositories(cfg: dict, store: dict, scanned: set[str]):
    hints = cfg.get("codeSearchHints") or []; ignored = set(cfg.get("ignoredRepositories") or [])
    for query in cfg.get("repositorySearches") or []:
        focused = any(k in query.lower() for k in ("quansheng", "uv-k", "uvk5", "uvk6", "f4hwn"))
        result = api_json(f"/search/repositories?q={urllib.parse.quote(query)}&sort=updated&order=desc&per_page=30")
        for repo in result.get("items", []):
            full = repo.get("full_name")
            if not full or full in ignored or full in scanned or repo.get("archived"): continue
            try:
                inspect_repo_python(full, repo.get("default_branch") or "main", hints, store,
                                    f"repository search: {query}", focused); scanned.add(full)
            except Exception as exc:
                print(f"warning: repo inspection failed for {full}: {exc}", file=sys.stderr)


def discover_pull_requests(cfg: dict, store: dict):
    hints = cfg.get("codeSearchHints") or []; ignored_prs = set(cfg.get("ignoredPullRequests") or [])
    for source in cfg.get("repositories") or []:
        if not source.get("watchOpenPullRequests"): continue
        repo = source["repo"]
        for pr in api_json(f"/repos/{repo}/pulls?state=open&sort=updated&direction=desc&per_page=100"):
            prn = pr.get("number")
            if f"{repo}#{prn}" in ignored_prs: continue
            for f in api_json(f"/repos/{repo}/pulls/{prn}/files?per_page=100"):
                path = f.get("filename") or ""
                if not path.startswith("chirp/drivers/") or not path.endswith(".py") or path.endswith("/fake.py") or path.endswith("/generic_xml.py"): continue
                raw_url = f.get("raw_url")
                if not raw_url: continue
                try:
                    data = raw_bytes(raw_url); text = data.decode("utf-8", errors="replace")
                except Exception: continue
                ok, found_hints = looks_like_driver(text, hints)
                if not ok: continue
                meta = extract_models(text)
                if not meta["models"]: continue
                add_candidate(store, {"candidateKey": f"pr:{repo}#{prn}:{path}", "type": "pull-request-file",
                    "repository": repo, "pullRequest": prn, "pullRequestTitle": pr.get("title") or "", "path": path,
                    "sourceUrl": pr.get("html_url"), "downloadUrl": raw_url, "sha256": hashlib.sha256(data).hexdigest(),
                    **candidate_metadata(meta), "hintsMatched": found_hints,
                    "reasons": ["open pull request in watched repository"], "status": "needs-review"})


def dedupe_exact_files(candidates: list[dict]) -> list[dict]:
    by_sha: dict[str, list[dict]] = {}
    for candidate in candidates: by_sha.setdefault(candidate.get("sha256") or candidate["candidateKey"], []).append(candidate)
    out = []; preferred_sources = ("mjwgeek/", "egzumer/", "armel/", "kk7ds/")
    for group in by_sha.values():
        if len(group) == 1: out.append(group[0]); continue
        def rank(item):
            repo = item.get("repository", ""); source_rank = next((i for i, p in enumerate(preferred_sources) if repo.startswith(p)), 99)
            return (source_rank, 0 if item.get("type") == "pull-request-file" else 1, repo.lower(), item.get("path", "").lower())
        group.sort(key=rank); keep = group[0]
        keep["duplicateSources"] = [{"repository": x.get("repository"), "path": x.get("path"), "sourceUrl": x.get("sourceUrl")} for x in group[1:]]
        reasons = set(keep.get("reasons", [])); reasons.add(f"collapsed {len(group) - 1} byte-identical duplicate source(s)"); keep["reasons"] = sorted(reasons); out.append(keep)
    return out


def main():
    cfg = json.loads(SOURCES.read_text(encoding="utf-8")); found = {}; scanned: set[str] = set()
    discover_pull_requests(cfg, found); discover_explicit_repositories(cfg, found, scanned)
    discover_owned_repositories(cfg, found, scanned); discover_repositories(cfg, found, scanned)
    candidates = dedupe_exact_files(list(found.values()))
    candidates.sort(key=lambda x: (x.get("repository", "").lower(), x.get("path", "").lower(), x.get("candidateKey", "")))
    payload = {"schemaVersion": 3, "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
               "candidateCount": len(candidates), "candidates": candidates}
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(candidates)} candidate(s) to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
