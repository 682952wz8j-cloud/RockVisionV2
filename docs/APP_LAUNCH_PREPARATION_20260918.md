# CragPal App 上线准备检查点（2026-09-18）

本检查点承接现有 Work 的调查、实现与验证结果。当前集中推进工作流 1（iOS 开发）、4（App Store 发布准备）和 5（合规准备）；工作流 2（首发岩壁数据）与 3（真机/现场验收）继续等待现场条件，不在本轮推进。

## 当前结论

工作流 1、4、5 的可离线完成部分已经完成。iOS 首次启动隐私同意、权限与重试流程、App 内政策入口、隐私清单、商店文案、审核说明、App 备案材料、网站 App 专用政策页，以及生产日志留存配置均已形成可审查结果。

Apple Developer Program 组织审批仍未完成，本机也没有有效代码签名身份，因此正式签名、Archive 上传、App Store Connect 配置提交，以及依赖正式分发证书 SHA-1 的 App 备案暂时不能执行。这些属于外部前置条件，不是代码或材料缺失。

## 1. iOS 开发

已完成：

- 在创建主界面、请求相机/定位权限或发起目录网络请求之前，加入按政策版本持久化的首次启动隐私同意门。
- 提供明确的同意与拒绝操作；拒绝时不进入应用主体。App 内可以重新查看政策并经确认撤回同意，撤回后返回隐私同意页。
- 修正相机与定位权限错误分类、定位超时和重复请求、目录加载并发与过期状态，以及 App 前后台切换时 AR 会话的暂停和恢复行为。
- 将定位说明统一为：精确 GPS 坐标只在本机用于选墙；下载请求发送选定的 `wallId`，服务端入口日志可能记录 IP、时间和请求路径。
- 更新 `PrivacyInfo.xcprivacy`，以保守方式声明诊断数据、粗略位置、电子邮箱和客户支持数据；所有条目均为非追踪用途。
- 新增相关单元测试和源码约束测试，覆盖隐私同意门、无同意时不发起目录网络请求、权限错误分类、重试与状态清理。

已完成验证：

- 针对 `ProductionPathTests` 与 `ScanLoadingTests` 的测试通过：37 个测试执行，2 个跳过，0 个失败。
- 测试结果：`/private/tmp/CragPalLaunchPrepDerivedData/Logs/Test/Test-RockVision-2026.09.18_20-27-48-+0800.xcresult`。
- 最新完整 `RockVisionTests` 回归通过：381 个测试执行，3 个跳过，0 个失败；结果位于 `/private/tmp/CragPalLaunchPrepFullTestsDerivedData/Logs/Test/Test-RockVision-2026.09.18_20-37-08-+0800.xcresult`。
- `Info.plist`、`Info.Debug.plist` 与 `PrivacyInfo.xcprivacy` 已通过 plist 语法检查。

最终检查：

- [x] Release 配置的通用 iOS 设备无签名构建通过，结果为 `BUILD SUCCEEDED`。产物位于 `/private/tmp/CragPalLaunchPrepReleaseDerivedData/Build/Products/Release-iphoneos/RockVision.app`，完整日志位于 `/private/tmp/cragpal-release-build-20260918.log`。
- [x] 最新 Release `.app` 已通过 `ios/scripts/verify_release_bundle.py`：`PASS: Release identity, ATS, file sharing, app manifest and pinned OpenCV privacy resource`。验证版本为 `2.0.0 (1)`。
- [x] 最新构建中 `CLLocationManagerDelegate`、`main actor` 和 `actor-isolated` 相关警告均为 0。其余警告来自既有 OpenCV/链接配置，不阻断本轮构建。

## 4. App Store 发布准备

发布与审核材料已经整理至：

- `outputs/app-launch-20260918/review/README.md`
- `outputs/app-launch-20260918/review/STORE_COPY.md`
- `outputs/app-launch-20260918/review/REVIEW_EXPERIENCE.md`
- `outputs/app-launch-20260918/review/SCREENSHOTS_AND_SUBMISSION.md`

材料包括中英文商店文案、TestFlight 文案、审核说明、截图要求和 Apple Developer 组织审批完成后的 11 步提交顺序。

当前审核口径保持真实：当前版本没有可供审核员离线替代真实岩壁扫描的完整现场体验，不会声称九龙峰已经上线。计划使用的“现场录制示例”必须来自真实现场录制，只用于帮助审核员理解流程，不能代替真机现场验收。现有 iPhone 17 Pro 1206 × 2622 截图属于 6.3 英寸规格，不能直接假定满足 App Store 要求的 6.9/6.5 英寸截图组；网站 AI 效果图不能作为 App Store 截图。

外部阻塞：

- Apple Developer Program 组织审批仍在等待。
- 本机 `security find-identity -v -p codesigning` 当前为 `0 valid identities found`。
- 在组织审批和正式证书可用前，不执行正式签名、Archive 上传或 App Store Connect 提交。

## 5. 合规准备

### App 隐私与支持

合规材料位于：

- `outputs/app-launch-20260918/privacy/AUDIT.md`
- `outputs/app-launch-20260918/privacy/APP-FILING.md`
- `outputs/app-launch-20260918/privacy/app-privacy.html`
- `outputs/app-launch-20260918/privacy/app-support.html`

App 内和网站 App 专用页面均使用公开联系邮箱 `z.zhang020@gmail.com`。网站一般联系邮箱 `hello@cragpal.com` 保持不变。App 隐私政策涵盖相机、精确 GPS、本机选墙、`wallId`、入口日志、支持邮件、服务提供方、保存期限、删除与撤回同意方式。

网站已经新增 `/app-privacy` 与 `/app-support` 页面，并在 Footer 中加入相应入口；原有网站 `/privacy` 内容保持不变。本地 TypeScript 和生产构建通过；ESLint 为 0 个错误、1 个既有 Fast Refresh 警告；桌面和 390 × 844 移动布局已完成可视检查。

线上检查：

- [x] 已按网站现有腾讯云原子发布方式部署至 `/var/www/cragpal-website/releases/v5-app-pages-20260918`，并将 `current` 从 `v4-brand-20260918` 切换至该版本；v4 保留作为回滚点。
- [x] `https://cragpal.com/app-privacy` 与 `https://cragpal.com/app-support` 均返回 200。线上 JavaScript SHA-256 与本地构建一致：`1b09a6968166146dfeb3692d1bff7768701ee68dd1ca48d7ac9220fe7647908b`。
- [x] 已验证政策正文、相互链接、`z.zhang020@gmail.com`、Footer 豹猫图标和 `京ICP备2026061092号-1` 至工信部备案官网的链接。
- [x] 首页与既有 `/privacy` 均返回 200；`www` 域名可访问；390 × 844 线上移动布局完成可视检查。

### 生产日志与留存

已在生产服务器部署并验证：

- Nginx 日志按天轮转，保留 190 份并压缩，满足相关网络日志不少于六个月的要求。
- journald 设置 `MaxRetentionSec=190day`、`MaxFileSec=1day`、`SystemMaxUse=8G` 和 `SystemKeepFree=10G`。
- `rockvision-api` Docker 日志限制为 `max-size=10m`、`max-file=5`，避免容器日志无限增长；对外入口所需日志由 Nginx 保留。
- 重启后本机和公网 `/health` 均返回 `{"status":"ok"}`，`systemd-journald` 与 `rockvision-api` 保持 active。

仓库中的对应配置与运行手册：

- `deploy/logrotate/nginx`
- `deploy/systemd/90-cragpal-retention.conf`
- `deploy/systemd/rockvision-api.service`
- `docs/PRIVACY_RETENTION_RUNBOOK.md`

支持邮件执行规则为：问题解决后，以最后一次联系为起点，最长保留 12 个月；法律、安全或争议处理例外另行记录；每季度执行一次人工检查。首次季度检查仍需按运行手册实际执行并留下记录。

### App 备案

App 备案尚未申请。网站备案号 `京ICP备2026061092号-1` 不能代替 App 备案。当前已确认：

- App 名称：CragPal
- Bundle ID：`com.rockvision.v2`
- App 备案联系邮箱：`z.zhang020@gmail.com`
- iOS 备案中的“签名 MD5”字段按腾讯云指引实际填写正式分发证书的 SHA-1 指纹。

由于正式分发证书只能在 Apple Developer 组织审批完成后确定，当前不得使用临时证书或猜测指纹提交。审批完成后的下一步是创建/下载正式分发证书、核对 SHA-1，再依照 `outputs/app-launch-20260918/privacy/APP-FILING.md` 提交备案。

## 保持等待的工作流

工作流 2（首发岩壁数据）和工作流 3（真机/现场验收）保持等待，直到用户能够前往现场。本轮不修改首发岩壁真实性结论，不用演示数据替代真实采集，也不把模拟器或录屏结果写成现场验收通过。

## 剩余上线顺序

1. 等待 Apple Developer Program 组织审批。
2. 创建并核对正式分发证书，取得 App 备案所需 SHA-1 后提交 App 备案。
3. 在 App Store Connect 填写商店元数据、App Privacy 回答和审核信息，上传正式 Archive/TestFlight 构建。
4. 用户具备现场条件后，恢复工作流 2 与 3，完成真实岩壁数据和真机现场验收，再决定提交审核的最终版本。
