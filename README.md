# PocketCHIRP CHIRP Engine 2.0

PocketCHIRP CHIRP Engine is the separately distributed GPL companion runtime used by PocketCHIRP 2.x.

Android package: `com.wg5eek.pocketchirp.engine`

## Architecture boundary

PocketCHIRP 2.x intentionally separates the PocketCHIRP Android application from the CHIRP runtime.

This engine repository contains:

- the vendored CHIRP runtime and CHIRP radio drivers;
- the minimized CHIRP-facing Python bridge;
- the engine-side Android service and Binder serial proxy;
- the neutral AIDL contract required to communicate with the PocketCHIRP app; and
- build and attribution material required to reproduce the engine.

It intentionally does **not** contain the PocketCHIRP editor/UI, billing or licensing UI, cloud-backup features, online radio-data features, favorites, Android USB implementation, Android BLE/GATT implementation, or PocketCHIRP proprietary native radio protocols.

The PocketCHIRP application communicates with this engine as a separate Android package/process. CHIRP code is not embedded in the PocketCHIRP application APK.

## CHIRP source

The engine currently vendors CHIRP at upstream commit:

`a229fae793154b10f602f7ea3d57d42dfa06e8f3`

Normal Gradle builds do not download CHIRP from pip or GitHub. The pinned source is included in `src/main/python/chirp`, and the build verifies the vendored commit before packaging.

## License

The CHIRP runtime and CHIRP-derived portions of this engine are distributed under the GNU General Public License, version 3. See `LICENSE` and `third_party/chirp/COPYING`.

This engine repository is the GPL component. The separate PocketCHIRP application is not offered under GPLv3 merely because it communicates with this separately distributed engine. See `POCKETCHIRP-LICENSE-NOTICE.md` for the project boundary and ownership notice.

## Corresponding source

Release tags for the engine should identify the exact source corresponding to each distributed engine APK/AAB. Do not publish a binary release whose corresponding engine source cannot be obtained from the matching tag/commit.

## Upstream project

CHIRP is an independent open-source amateur-radio programming project. PocketCHIRP is not affiliated with or endorsed by the CHIRP project.
