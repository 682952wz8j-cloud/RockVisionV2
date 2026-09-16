# Release preparation — 2026-09-16

This is a release-preparation checkpoint, not App Store submission approval or a Gate PASS.
Base development commit: `0b563dcc5d0f548aec317e17905658b1e734cc77`.

## Product and configuration

- User approved Release scan UI and isolation of engineering controls, privacy resources, permissions, support, and review/merge to main.
- Release displays the scan HUD and crag sidebar. Engineering panels, FieldTest controller initialization, restored field sessions and field sample sink wiring are DEBUG-only.
- App identity remains `com.rockvision.v2`, `2.0.0 (1)`, team `P767DBUSNG`, automatic signing. No evidence from App Store Connect justifies changing them yet. The sidebar reads the actual bundle version.
- Release uses HTTPS and no ATS HTTP exception; Debug uses `Info.Debug.plist` for the existing development IP endpoint. Release file sharing is disabled; Debug field exports remain available.
- App PrivacyInfo declares sandbox file timestamp access (C617.1), no tracking, and operational network information as Other Data / App Functionality / not linked. Verify production logging and ASC privacy questionnaire together before submission; do not claim that no server-side data exists.
- The pinned OpenCV static archive is unchanged. Its upstream privacy manifest is copied byte-for-byte into `OpenCVPrivacy.bundle`; resource-bundle Info.plist makes it independently identifiable. Check this copy against the pinned XCFramework whenever rebuilding the SDK. No framework binary is embedded or repinned.
- Offline Chinese privacy policy and support are available from the sidebar, with the user-supplied company and email. Public page sources are in `deploy/public/`. Intended URLs: `https://www.cragpal.com/privacy.html` and `https://www.cragpal.com/support.html`. Website DNS did not resolve during this audit; the pages have NOT been deployed. App support uses email and does not depend on website availability.
- No subscription/IAP implementation or cloud package change is included.

## Evidence and unchanged Gate status

Repository README and DEVELOPMENT_GATES remain authoritative for formal Gate closure. Their historical Stage 5 status has NOT been changed to PASS. Both current packages still declare `routeArReady: false`; this flag is not overwritten to manufacture readiness.

Observed on 2026-09-16:
- HTTPS production catalog returned Jinshidong r000001 and Jiulongfeng r000002.
- Both immutable manifest JSONs matched tracked package manifests.
- Both wall-routes and s-wall-colmap assets matched manifest sizes and SHA-256.
- Full descriptor downloads exceeded a 90-second audit timeout. Full-package delivery and device installation remain unverified, not proven corrupt.
- No new Release/iPhone field acceptance or Gate 5D-B/5E closure was found. Historical test zip files are not evidence for the current build.

Required field evidence: exact main commit + app version/build + device/iOS + wallId/releaseId; fresh TestFlight installation, cloud download, visual match/PnP, physical route alignment, tracking loss/relocalization, permission denial, interrupted download and app lifecycle behavior. Physical acceptance and human Gate closure remain required.

## Remaining release gates

1. Confirm App Store Connect bundle ID, unused build number, account agreements and distribution signing; archive/validate/upload has not been completed.
2. Make the two website pages publicly available via valid HTTPS; reconcile server log retention/access practices with the policy and privacy answers.
3. Verify App ICP number, company/name metadata, screenshots, age rating, export compliance, support/privacy URLs and review contact.
4. Internal TestFlight field acceptance, documented review access outside the 2.5 km GPS selection radius, then first external Beta App Review and field test.
5. Close only gates supported by evidence, select that same build for App Review, then manual public release.

A local RC-preparation tag pins source for further verification. It does not certify readiness, sign/upload the app, publish a package, or push to GitHub.

## Validation of this change

- Device arm64 Release build: PASS, Xcode 26.6 / iOS 26.5 SDK, signing disabled.
- arm64 simulator Release build: PASS. The initial universal simulator build requested x86_64, which the pinned OpenCV does not support; the successful retry explicitly selected arm64 without changing project configuration.
- `ios/scripts/verify_release_bundle.py`: PASS against both device and simulator Release products.
- Existing iOS regression suites: 106 executed, 3 skipped, 0 failures (103 passed). Skips were the physical-device Documents export and two opt-in live HTTPS tests.
- Manual simulator Release UI check: product scan screen and sidebar present, version 2.0.0, no Gate 4B panel, privacy/support sheet opens after denying location; company, email, and Chinese policy text are readable. Simulator is not AR/physical-alignment evidence.
- Independent read-only review: no merge-blocking defect introduced by this change; all privacy/plist resources parse; upstream OpenCV manifest is byte-identical.
- Known pre-existing behavior: returning from Settings after granting location does not restart production loading; users may need to restart the app. Location denial is currently reported using a generic network error. Neither recovery nor error copy is represented as fixed by this change.
- Broad `rockvision verify` attempts were deliberately stopped after entering real COLMAP reconstruction (including a 47-image regression). These attempts have no passing result. The narrower publishing/catalog/production-package suite is recorded separately; this is not a full verify PASS.

## Final contract check and source merge

- Seven targeted Python suites ran 135 tests in 127.373 seconds: 132 passed, 2 failed, 1 skipped. The two failures are pre-existing live expectations for Jiulongfeng r000001 / route name instead of the deployed r000002 / updated route name. They are NOT marked PASS or silently rewritten in this change.
- The live Jiulongfeng test downloaded all four r000002 assets and verified every byte count and SHA-256 before reaching the stale route-name assertion. This upgrades Jiulongfeng full cloud asset integrity evidence; it does not prove iPhone installation, remaining downstream assertions, or physical route alignment. Jinshidong full-download evidence remains incomplete.
- Main merge: `2f5bb3a69068383e13050601736741c329fa48c6`, with the same file tree as reviewed implementation `7ce034f`. Origin main was checked at `c8b25f44a5889489b1984e17122a152850d9a49c`; no remote push was performed.
- The release-preparation source checkpoint is tagged `cragpal-2.0.0-rc-prep.1`. It remains a preparation candidate, NOT a submission-ready RC, because tests/evidence and external release prerequisites listed above remain open.

## Follow-up: TestFlight preparation

- User authorized correcting the two stale live tests, pushing main and candidate tags, signing/archive, and uploading for internal TestFlight.
- Only the two live expectations were updated: catalog must select r000002; its complete manifest and route asset must equal the tracked frozen r000002 files. Historical r000001 construction tests remain unchanged. All hash, byte-count, Sim(3), route identity and frozen geometry assertions remain.
- Jiulongfeng suite: all 10 tests PASS in 122.464 seconds, including full live HTTPS asset download and integrity checks. The two previous stale-expectation failures are resolved. Full COLMAP verify and physical acceptance remain open.
- Release 2.0.0 (1) signed Archive generated successfully at `/private/tmp/CragPal-2.0.0-1.xcarchive`. Actual archived app passed release-resource validation and `codesign --verify --deep --strict` with host keychain access. This is development-signed archive evidence, not App Store distribution/export evidence.
- Apple Developer account showed the Join Apple Developer Program prompt; user confirmed no program enrollment yet and intends organization enrollment. App Store Connect reports INVALIDITCUSER. Distribution export/upload and internal TestFlight are blocked on organization membership activation. No upload has been completed.
- New source checkpoint: `cragpal-2.0.0-rc-prep.2`; retain prep.1 as historical. App source/config is unchanged from the verified archive; this follow-up changes only tests and release records.
