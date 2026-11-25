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
