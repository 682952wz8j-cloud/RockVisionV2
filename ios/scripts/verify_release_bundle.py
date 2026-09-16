#!/usr/bin/env python3
"""Validate the actual Release app, not just Xcode source settings."""
import argparse
import plistlib
from pathlib import Path

def read(path):
    with path.open('rb') as stream:
        return plistlib.load(stream)

def verify(app, repo):
    info = read(app / 'Info.plist')
    assert info['CFBundleIdentifier'] == 'com.rockvision.v2'
    assert info['CFBundleDisplayName'] == 'CragPal'
    ats = info['NSAppTransportSecurity']
    assert ats.get('NSAllowsArbitraryLoads') is False
    assert not ats.get('NSExceptionDomains'), 'Release must not ship development HTTP exceptions'
    assert info.get('UIFileSharingEnabled') is False
    manifest = read(app / 'PrivacyInfo.xcprivacy')
    assert manifest['NSPrivacyTracking'] is False
    reasons = {x['NSPrivacyAccessedAPIType']: x['NSPrivacyAccessedAPITypeReasons'] for x in manifest['NSPrivacyAccessedAPITypes']}
    assert 'C617.1' in reasons['NSPrivacyAccessedAPICategoryFileTimestamp']
    resource = app / 'OpenCVPrivacy.bundle'
    assert read(resource / 'Info.plist')['CFBundlePackageType'] == 'BNDL'
    upstream = repo / 'ios/Vendor/OpenCV/opencv2.xcframework/ios-arm64/opencv2.framework/Versions/A/Resources/PrivacyInfo.xcprivacy'
    assert (resource / 'PrivacyInfo.xcprivacy').read_bytes() == upstream.read_bytes(), 'Pinned SDK privacy manifest mismatch'
    assert not (app / 'Frameworks/opencv2.framework/opencv2').exists(), 'Do not embed the static archive'
    assert 'Visual localization is not running' not in info['NSCameraUsageDescription']
    print('PASS: Release identity, ATS, file sharing, app manifest and pinned OpenCV privacy resource')
    print(f"Version {info['CFBundleShortVersionString']} ({info['CFBundleVersion']}); SDK {info.get('DTSDKName', 'unknown')}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=Path)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    verify(args.app, args.repo)
