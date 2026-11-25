#!/usr/bin/env python3
"""Refresh approved public talkgroup and DVRef directory snapshots. No subscriber data."""
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
# Full public registry is deliberately separate from the numeric contact manifest.
DVREF_CATALOG = {
    "dmr": ("dmr/networks", "networks"),
    "m17": ("mrefd/reflectors", "reflectors"),
    "nxdn": ("nxdn/reflectors", "reflectors"),
    "p25": ("p25/reflectors", "reflectors"),
    "urfd": ("urfd/reflectors", "reflectors"),
    "vex": ("vex/servers", "servers"),
    "ysf": ("ysf/reflectors", "reflectors"),
}
def recent(path):
    try:
        obj = json.loads(path.read_text())
        stamp = obj.get("pocketchirp", {}).get("checked_at") or obj.get("updated")
        age = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(stamp)).total_seconds()
        return 0 <= age < 6 * 3600
    except (OSError, ValueError, TypeError, AttributeError):
        return False
def write_json(target, payload):
    target.parent.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(f.name, target)
def refresh_catalog(manifest, get_response, responses, failures):
    for ident in manifest.get("dvref_catalog", []):
        try:
            route, key = DVREF_CATALOG[ident]
            endpoint = "https://dvref.com/api/v2/" + route + "/"
            target = ROOT / "dvref" / (ident + ".json")
            numeric = ROOT / "snapshots" / ("dvref-" + ident + ".json")
            if endpoint not in responses and (recent(target) or recent(numeric)):
                print("dvref-catalog-" + ident, "six-hour cache window; no request")
                continue
            envelope = json.loads(get_response(endpoint))
            metadata = envelope.get("_dvref_metadata", {})
            if envelope.get("status") != "success" or metadata.get("license", {}).get("spdx_id") != "CC-BY-4.0" or metadata.get("aup_url") != "https://dvref.com/aup/":
                raise ValueError("DVRef response missing expected license or status")
            data = envelope.get("data")
            items = data.get(key) if isinstance(data, dict) else None
            if not isinstance(items, list) or not 1 <= len(items) <= 20000 or not all(isinstance(x, dict) and x for x in items):
                raise ValueError("Missing or malformed public collection: " + key)
            if target.exists():
                old = json.loads(target.read_text())
                if len(items) < len(old["data"][key]) * 0.5:
                    raise ValueError("Unexpected directory shrink; retain prior snapshot")
            # Preserve the public records and original upstream license metadata.
            envelope["pocketchirp"] = {
                "upstream": endpoint,
                "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "changes": "Public collection records unchanged; added PocketCHIRP cache metadata.",
                "attribution": "Reflector data provided by DVRef — https://dvref.com/",
                "license": "CC-BY-4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
            }
            write_json(target, envelope)
            print("dvref-catalog-" + ident, len(items))
        except Exception as exc:
            failures.append("dvref-catalog-" + str(ident) + ": " + str(exc))

def main():
    manifest = json.loads((ROOT/"manifest.json").read_text())
    responses = {}
    errors = {}
    failures = []
    def get_response(endpoint):
        if endpoint in errors: raise errors[endpoint]
        if endpoint not in responses:
            try: responses[endpoint] = download(endpoint)
            except Exception as exc:
                errors[endpoint] = exc
                raise
        return responses[endpoint]
    for s in manifest["sources"]:
        if s["delivery"] != "mirror": continue
        try:
            ident=s["id"]
            if not re.fullmatch(r"[a-z0-9_-]+",ident) or s["mode"] not in MAX: raise ValueError("Invalid source")
            a=s.get("approval") or {}
            if s.get("redistribution") != "approved" or not all(a.get(k) for k in ("evidence","license","commercial_use")) or a["commercial_use"] is not True: raise ValueError("Missing recorded commercial redistribution approval")
            if s.get("snapshot") != f"snapshots/{ident}.json": raise ValueError("Invalid snapshot path")
            target=ROOT/s["snapshot"]
            if s["format"] == "dvref" and (recent(target) or recent(ROOT/"dvref"/(s["mode"].lower()+".json"))):
                print(ident, "six-hour cache window; no request")
                continue
            rows=normalize(get_response(s["endpoint"]),s["format"],s["mode"])
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
    refresh_catalog(manifest, get_response, responses, failures)
    if failures: raise SystemExit("\n".join(failures))
if __name__ == "__main__": main()
