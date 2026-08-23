# OpenCV for iOS

Pinned at Gate 3A. Do not float.

The XCFramework **binary is not in Git**. After clone, rebuild it before
opening the Xcode app/test targets.

| Field | Value |
|-------|--------|
| Version | 4.14.0 |
| Tag | `4.14.0` |
| Commit | `0654a42e19215ef25b1d367d822f3c630447e7c7` |
| Tool | official `platforms/apple/build_xcframework.py` |
| Install path | `ios/Vendor/OpenCV/opencv2.xcframework` |
| Zip SHA-256 | `ec10b74646b0cd51e3897c3ddbcfeb3c0ab3ba931ca374aaa9a6b19efd3c780a` |

See [docs/OPENCV_IOS_BUILD.md](../../../docs/OPENCV_IOS_BUILD.md).

## After a fresh clone

1. Read `VERSION.txt` and `SOURCE_COMMIT.txt` for the exact pin.
2. Need CMake ≥ 3.18.5 on `PATH` (this pin was built with CMake 4.4.2).
3. Rebuild:

```text
ios/Vendor/OpenCV/build_opencv_xcframework.sh
```

The script clones tag `4.14.0`, checks out commit
`0654a42e19215ef25b1d367d822f3c630447e7c7`, runs Apple
`build_xcframework.py`, and copies the result to
`ios/Vendor/OpenCV/opencv2.xcframework`.

4. Verify (must match `opencv2.xcframework.sha256` / `VERSION.txt`):

```text
ditto -c -k --keepParent ios/Vendor/OpenCV/opencv2.xcframework /tmp/opencv2.xcframework.zip
shasum -a 256 /tmp/opencv2.xcframework.zip
# expected: ec10b74646b0cd51e3897c3ddbcfeb3c0ab3ba931ca374aaa9a6b19efd3c780a
```

5. If `opencv2.xcframework` is missing, Xcode cannot link `opencv2`.
   App and `RockVisionTests` fail at the Frameworks / link step with a
   missing `opencv2.xcframework` (or missing `opencv2` binary). That is
   expected until the script above has been run.

```text
ios/Vendor/OpenCV/
  opencv2.xcframework          # gitignored; rebuild locally
  VERSION.txt                  # tag, commit, command, archs, modules, SHA-256
  SOURCE_COMMIT.txt
  opencv2.xcframework.sha256
  SIFT_PNP_VERIFY.txt
  build_opencv_xcframework.sh
  opencv/                      # gitignored source clone
  build/                       # gitignored build tree
```

Do not drop in an unverified prebuilt framework from the internet.
