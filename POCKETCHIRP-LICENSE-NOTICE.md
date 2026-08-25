# PocketCHIRP Licensing and GPL Boundary Notice

## PocketCHIRP is not distributed as GPLv3 software

PocketCHIRP and PocketCHIRP CHIRP Engine are separate Android application packages with separate responsibilities and separately maintained source trees.

The **PocketCHIRP CHIRP Engine** contains the GNU GPLv3-licensed CHIRP runtime, CHIRP radio drivers, and the integration code needed for that engine to expose CHIRP functionality through a narrow inter-process interface. The engine is distributed separately and its corresponding source code is made available under the applicable GPLv3 terms.

The **PocketCHIRP application** is a separate application. Its user interface, Android USB and Bluetooth implementations, online-data integrations, licensing and billing code, backup and file-management features, satellite and utility features, proprietary native radio support, and other PocketCHIRP-specific code are not part of the CHIRP Engine and are not offered under GPLv3 unless a specific file states otherwise.

PocketCHIRP does not embed the CHIRP Python runtime or bundled CHIRP driver tree in the PocketCHIRP application APK. Instead, PocketCHIRP communicates with the separately installed CHIRP Engine through an Android Binder/AIDL boundary and passes transport/data requests across that process boundary.

Accordingly, the presence and distribution of GPLv3-licensed CHIRP code in the separate PocketCHIRP CHIRP Engine should not be read as a statement that the separate PocketCHIRP application is itself licensed under GPLv3. No GPL license is granted for independently authored PocketCHIRP application code except where an individual source file or component expressly states otherwise.

## Copyright and reserved rights

Except for third-party and open-source components identified by their own notices and licenses, PocketCHIRP-specific source code, artwork, branding, documentation, and other original materials remain the property of their respective copyright holder(s). All rights not expressly granted are reserved.

The names **PocketCHIRP**, PocketCHIRP branding, logos, artwork, and associated product identity are not licensed under GPLv3 merely because GPL-licensed software is used by a separate companion component.

## CHIRP and other third-party software

CHIRP is an independent open-source project and is licensed by its respective copyright holders under the GNU General Public License, version 3. PocketCHIRP is not affiliated with or endorsed by the CHIRP project.

Third-party code retains its original copyright and license. Nothing in this notice attempts to alter, restrict, or supersede rights granted by the GPLv3 or any other third-party license.

## Source availability for the GPL component

Corresponding source for distributed versions of the PocketCHIRP CHIRP Engine should be made available from the public engine source repository, with release tags or commits that correspond to distributed engine versions. The source distribution should include the applicable GPL license text and third-party notices.

## Scope of this notice

This notice documents the project's intended licensing and architectural boundary. It is not intended to modify the terms of the GNU GPL or any third-party license, and it is not a substitute for legal advice about whether particular code constitutes a derivative or combined work under applicable law.
