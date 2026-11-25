# PocketCHIRP digital directory registry

Independent provider registry and permission-gated snapshot updater. This is not a copy of W0CHP or Pi-Star lists. No user/subscriber records are published. All source licenses remain separate from PocketCHIRP.

- `direct`: user-requested official provider download, not public redistribution. Local caching only. Direct endpoints and parsers require Android testing; availability and terms may change.
- `pending`: no automated request; use a legally obtained local CSV. Do not interpret these entries as enabled integrations.
- `mirror`: may be enabled only after confirming both redistribution and use in a commercial application. Set `redistribution: "approved"`, `approval: {"evidence":"URL or permission record","license":"license identifier or terms","commercial_use":true}`, and `snapshot: "snapshots/<id>.json"`. Retain any required license/attribution notices alongside the snapshot. Review whether license covers the data, not merely API code.
- RadioID explicitly prohibits public mirroring without written permission: https://radioid.net/api/. User CSV remains local to the user's device.
- FreeSTAR's public API fair-use and GPL notice: https://freestar.network/services/. Confirm the license scope for returned directory data before enabling a mirror.
- FreeDMR and AmComm offer public exports; public downloads alone are not a blanket redistribution license.
- BrandMeister and TGIF endpoint candidates must be verified on-device before release; public access is not proof of mirror permission.

Run `python3 community/digital-directories/refresh.py` after approving sources. It does not fetch pending or direct-only providers. It validates output, refuses redirects and suspiciously truncated results, keeps prior good snapshots, and avoids changing unchanged files. An approved source will be fetched once per refresh run, not once per app installation. DMR/P25/NXDN contact IDs share one radio table; different networks can conflict. This is a group-call directory, not a caller-ID database.

## DVRef snapshots

Reflector data provided by DVRef — https://dvref.com/  
License: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). [DVRef AUP, effective 4 August 2026](https://dvref.com/aup/). DVRef does not endorse PocketCHIRP.

P25 and NXDN public reflector lists are normalized to numeric group contacts; names and IDs are extracted, other fields and out-of-range IDs omitted. The GitHub workflow fetches each approved resource once daily at 09:27 UTC, using the documented software, callsign and contact headers. No authentication token, HTML scraping, rapid retries or client-side requests to DVRef. Failed or malformed responses leave the last valid snapshot intact. App clients download from this repository. Manual runs must respect the six-hour upstream retrieval interval; do not rerun repeatedly after a 429. DMR network listings are not talkgroup directories; YSF, M17, URFD and VEX need distinct protocol-aware models and are not imported as numeric group contacts. Other provider entries retain their existing licensing status.

### Full DVRef catalog

The manifest's separate `dvref_catalog` list enables all seven public collections: DMR networks, M17/MREFD, NXDN, P25, URFD, VEX servers, and YSF. Files are published under `dvref/<mode>.json` with public collection records and upstream licensing metadata preserved, plus PocketCHIRP retrieval metadata. They are not numeric contact files. Only the compatible P25 and NXDN normalized snapshots are exposed by the current Android contact importer. DMR networks must not be treated as talkgroups, and other modes need protocol-specific app/firmware support.

The refresh job shares a single upstream response per resource between full and normalized snapshots. Recently retrieved P25/NXDN resources are not fetched again during initial catalog expansion; their full files appear after the six-hour cache window. Daily scheduling and manual refreshes should respect DVRef limits; never retry rapidly or bypass a 429. Last good files remain available if a collection fails.
