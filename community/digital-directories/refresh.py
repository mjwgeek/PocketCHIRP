#!/usr/bin/env python3
"""Refresh only explicitly approved, public talkgroup snapshots. No subscriber data."""
import csv, datetime, io, json, os, pathlib, re, tempfile, urllib.request
from urllib.parse import urlsplit
ROOT = pathlib.Path(__file__).resolve().parent
LIMIT = 8 * 1024 * 1024
HOSTS = {"api.brandmeister.network", "tgif.network", "tg.freedmr.uk", "amcomm.network", "api.freestar.network", "dvref.com"}
MAX = {"DMR": 16777214, "P25": 65534, "NXDN": 65519}
def allowed(url):
    u = urlsplit(url)
    return u.scheme == "https" and u.hostname in HOSTS and not u.username and not u.password and u.port in (None, 443)
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirect requires manual source review")
def download(url):
    if not allowed(url):
        raise ValueError("Unapproved upstream hostname")
    req = urllib.request.Request(url, headers={"User-Agent": "PocketCHIRP Directory Cache (+https://pocketchirp.com)", "Accept": "application/json,text/csv"})
    if urlsplit(url).hostname == "dvref.com":
        req.add_header("User-Agent", "PocketCHIRP/2.11.1")
        req.add_header("X-DVRef-Callsign", "WG5EEK")
        req.add_header("X-DVRef-Contact", "https://pocketchirp.com/")
    with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as resp:
        data = resp.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError("Oversized response")
        return data.decode("utf-8-sig")
def normalize(text, fmt, mode):
    rows = {}
    def add(id_, name):
        if isinstance(id_, bool) or not re.fullmatch(r"[0-9]{1,8}", str(id_)):
            return
        num = int(id_)
        if not 1 <= num <= MAX[mode] or not isinstance(name, str) or not name.strip():
            return
        name = " ".join(name.split())[:160]
        if num in rows and rows[num] != name:
            raise ValueError(f"Conflicting names for {num}")
        rows[num] = name
    def walk(x):
        if isinstance(x, list):
            for v in x: walk(v)
        elif isinstance(x, dict):
            if fmt == "freestar":
                if str(x.get("mode","")).upper() == mode and x.get("kind") in ("talkgroup","reflector"):
                    add(x.get("key"), x.get("name"))
            else:
                id_ = next((x[k] for k in ("tgid","talkgroup","tg","id","TGID","Talkgroup","TalkGroup") if k in x), None)
                name = next((x[k] for k in ("name","callsign","description","label","Name","TGName","TalkgroupName") if k in x), None)
                add(id_, name)
            for v in x.values():
                if isinstance(v,(dict,list)): walk(v)
    if fmt == "csv":
        for row in csv.DictReader(io.StringIO(text)):
            norm = {re.sub(r"[^a-z0-9]", "", k.lower()): v for k,v in row.items() if k}
            add(next((norm[k] for k in ("tgid","talkgroup","id","tg") if k in norm),None),next((norm[k] for k in ("name","talkgroupname","description","callsign") if k in norm),None))
    elif fmt == "dvref":
        envelope = json.loads(text)
        metadata = envelope.get("_dvref_metadata", {})
        if envelope.get("status") != "success" or metadata.get("license", {}).get("spdx_id") != "CC-BY-4.0" or metadata.get("aup_url") != "https://dvref.com/aup/":
            raise ValueError("DVRef response missing expected license or status")
        items = envelope["data"]["reflectors"]
        if not isinstance(items, list) or not items:
            raise ValueError("DVRef reflector list missing")
        for item in items:
            if not isinstance(item, dict): raise ValueError("Invalid reflector record")
            # Only explicit talkgroup/designator fields, never database PK, port or slug.
            value = item.get("talkgroup", item.get("designator"))
            match = re.fullmatch(r"(?:" + mode + r"[- ]?)?([0-9]{1,8})", str(value), re.I)
            if not match:
                raise ValueError("Unrecognized DVRef " + mode + " talkgroup designator")
            n = int(match.group(1))
            if not 1 <= n <= MAX[mode]: continue
            name = item.get("name") or item.get("description") or f"{mode} {n}"
            add(n, name)
    elif fmt == "bm-map":
        for k,v in json.loads(text).items(): add(k,v)
    elif fmt in ("objects","freestar"):
        walk(json.loads(text))
    else:
        raise ValueError("Unsupported format")
    if not rows or len(rows)>20000: raise ValueError("Invalid row count")
    return [{"id":k,"name":v} for k,v in sorted(rows.items())]
def main():
    manifest = json.loads((ROOT/"manifest.json").read_text())
    responses = {}
    failures = []
    for s in manifest["sources"]:
        if s["delivery"] != "mirror": continue
        try:
            ident=s["id"]
            if not re.fullmatch(r"[a-z0-9_-]+",ident) or s["mode"] not in MAX: raise ValueError("Invalid source")
            a=s.get("approval") or {}
            if s.get("redistribution") != "approved" or not all(a.get(k) for k in ("evidence","license","commercial_use")) or a["commercial_use"] is not True: raise ValueError("Missing recorded commercial redistribution approval")
            if s.get("snapshot") != f"snapshots/{ident}.json": raise ValueError("Invalid snapshot path")
            if s["endpoint"] not in responses: responses[s["endpoint"]] = download(s["endpoint"])
            rows=normalize(responses[s["endpoint"]],s["format"],s["mode"])
            target=ROOT/s["snapshot"]
            if target.exists():
                old=json.loads(target.read_text())
                if len(rows)<len(old["rows"])*0.5: raise ValueError("Unexpected directory shrink; retain prior snapshot")
                if old["rows"]==rows and old.get("approval")==a: print(ident,"unchanged"); continue
            payload={"schema":1,"id":ident,"mode":s["mode"],"type":"Group","source":s["name"],"upstream":s["endpoint"],"approval":a,"updated":datetime.datetime.now(datetime.timezone.utc).isoformat(),"rows":rows}
            if s["format"] == "dvref":
                payload.update({"attribution": "Reflector data provided by DVRef — https://dvref.com/", "license": "CC-BY-4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/", "changes": "Normalized numeric reflector IDs and names; omitted unsupported IDs and other fields."})
            target.parent.mkdir(exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as f:
                json.dump(payload,f,ensure_ascii=False,indent=2); f.write("\n")
            os.replace(f.name,target)
            print(ident,len(rows))
        except Exception as exc:
            failures.append(ident+": "+str(exc))
    if failures: raise SystemExit("\n".join(failures))
if __name__ == "__main__": main()
