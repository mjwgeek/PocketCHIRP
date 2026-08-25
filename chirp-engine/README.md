# PocketCHIRP CHIRP Engine — GPL companion candidate

This module is intentionally a separate Android application package:
`com.wg5eek.pocketchirp.engine`.

It contains only:
- CHIRP and CHIRP-compatible drivers,
- the minimized CHIRP-facing `bridge.py`,
- the neutral AIDL engine contract,
- the engine-side Binder serial proxy,
- CHIRP image/object/clone adapters.

It intentionally contains no PocketCHIRP UI, WebView, billing, cloud backup,
network data sources, favorites, community-driver discovery/download code,
Android USB implementation, Android BLE/GATT implementation, or proprietary
native-radio protocols.

The service is protected by a signature-level permission. If the Play and
engine APKs are signed differently, replace this with explicit caller-package
and certificate verification before production distribution.
