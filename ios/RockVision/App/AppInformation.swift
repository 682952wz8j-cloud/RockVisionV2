import SwiftUI

enum PrivacyConsent {
    static let storageKey = "privacy-consent-version"
    static let currentVersion = 20260918
    static let policyURL = URL(string: "https://cragpal.com/app-privacy")!
    static let supportPageURL = URL(string: "https://cragpal.com/app-support")!

    static func isGranted(version: Int) -> Bool {
        version == currentVersion
    }
}

struct PrivacyConsentGate: View {
    @Binding var consentVersion: Int
    @State private var declined = false

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text("使用 CragPal 前")
                        .font(.largeTitle.bold())
                        .foregroundStyle(.white)
                    Text("请阅读并选择是否同意隐私政策。在你明确同意前，CragPal 不会请求相机或定位权限，也不会下载岩场数据。")
                        .foregroundStyle(.white.opacity(0.86))

                    VStack(alignment: .leading, spacing: 14) {
                        privacyLine(
                            icon: "camera",
                            title: "相机",
                            detail: "用于识别岩壁和显示路线；图像与视频仅在设备上处理，不上传到我们的服务器。"
                        )
                        privacyLine(
                            icon: "location",
                            title: "位置",
                            detail: "GPS 经纬度仅在设备上用于选择附近已支持岩场，不上传到我们的服务器；下载请求会包含所选岩场标识。"
                        )
                        privacyLine(
                            icon: "network",
                            title: "网络",
                            detail: "用于下载岩场目录和路线数据；服务器会接收 IP 地址、请求时间和资源路径等必要网络信息。"
                        )
                    }
                    .padding(18)
                    .background(.white.opacity(0.09), in: RoundedRectangle(cornerRadius: 18))

                    Link("阅读完整隐私政策", destination: PrivacyConsent.policyURL)
                        .font(.headline)

                    Text("点击“同意并继续”，表示你同意上述必要处理。你可以之后在 App 的“隐私政策与支持”中撤回同意。")
                        .font(.callout)
                        .foregroundStyle(.white.opacity(0.72))
                    if declined {
                        Text("你选择了暂不同意。App 将保持停用，也不会请求权限或下载数据。你可以随时在本页重新选择。")
                            .font(.callout)
                            .foregroundStyle(.white.opacity(0.72))
                    }

                    VStack(spacing: 12) {
                        Button {
                            consentVersion = PrivacyConsent.currentVersion
                            declined = false
                        } label: {
                            Text("同意并继续")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                        .accessibilityIdentifier("privacy-consent-accept")

                        Button("暂不同意") {
                            consentVersion = 0
                            declined = true
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.large)
                        .accessibilityIdentifier("privacy-consent-decline")
                    }
                    .frame(maxWidth: .infinity)
                }
                .padding(.horizontal, 24)
                .padding(.vertical, 48)
                .frame(maxWidth: 560, alignment: .leading)
                .frame(maxWidth: .infinity)
            }
        }
        .tint(Color(red: 0.76, green: 1, blue: 0.1))
    }

    private func privacyLine(icon: String, title: String, detail: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .frame(width: 24)
                .foregroundStyle(Color(red: 0.76, green: 1, blue: 0.1))
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.headline)
                Text(detail)
                    .font(.callout)
                    .foregroundStyle(.white.opacity(0.72))
            }
            .foregroundStyle(.white)
        }
    }
}

/// Available offline, including when location or network access is unavailable.
struct AppInformationView: View {
    @Environment(\.dismiss) private var dismiss
    @AppStorage(PrivacyConsent.storageKey) private var privacyConsentVersion = 0
    @State private var showsRevokeConfirmation = false
    private let supportURL = URL(string: "mailto:z.zhang020@gmail.com?subject=CragPal%20Support")!

    var body: some View {
        NavigationStack {
            List {
                Section("使用帮助") {
                    Text("请在已支持的岩场打开 CragPal，允许相机和定位权限，并在有网络时完成岩场数据下载，然后将相机对准岩壁。")
                    Text("无法定位时，请确认位于已支持岩场附近、相机无遮挡且光线充足。下载失败时请检查网络后重新打开 App。")
                    Text("路线叠加仅作信息参考；请结合现场线路标识核对。")
                    Link("邮件联系支持", destination: supportURL)
                    Text("z.zhang020@gmail.com").textSelection(.enabled)
                    Text("发送问题时可说明设备型号、系统版本、App 版本和岩场名称。")
                }
                Section("隐私同意") {
                    Link("查看完整隐私政策", destination: PrivacyConsent.policyURL)
                    Link("查看公开支持页面", destination: PrivacyConsent.supportPageURL)
                    Text("撤回后，CragPal 会立即返回隐私同意页；再次同意前不会启动扫描或下载岩场数据。")
                    Button("撤回隐私同意并停止使用", role: .destructive) {
                        showsRevokeConfirmation = true
                    }
                }
                Section("运营者与联系") { Text("CragPal 由北京榫卯管理咨询有限公司运营。隐私问题和技术支持请联系 z.zhang020@gmail.com。更新日期：2026 年 9 月 18 日。").textSelection(.enabled) }
                Section("相机与位置") { Text("相机画面用于在设备上识别岩壁、计算视觉定位并显示路线；本版本不会将相机图像或视频自动上传至我们的服务器。GPS 经纬度仅在设备上用于选择附近已支持的岩场，不上传至我们的服务器，也不用于计算路线的精确叠加位置。下载请求会包含所选岩场标识，因此服务器能够知道本次请求对应哪个岩场。你可以在系统设置中关闭相机或定位权限；关闭后相应功能将无法使用。").textSelection(.enabled) }
                Section("网络与设备存储") { Text("App 通过 HTTPS 下载岩场目录和路线资源。服务器会接收 IP 地址、请求时间、资源路径、响应状态和错误等必要网络信息，用于提供内容、保障服务和排查故障。本地会保存已下载的岩场资源，以及下载或安装失败时的诊断记录；本版本不会自动上传这些本地诊断记录。删除 App 可以移除设备上的本地数据，但不会删除服务器已有日志或你曾发送的支持邮件。").textSelection(.enabled) }
                Section("共享、保存与删除") {
                    Text("本版本没有广告、账户注册、订阅购买或第三方行为统计功能。腾讯云提供网络托管和资源存储，外部邮件服务用于接收你主动发送的支持邮件。在我们委托服务商处理数据的范围内，我们通过适用协议要求其提供与本政策及适用规则相同或相当的保护；我们不授权其将这些信息用于广告追踪。入口代理访问日志按日轮转并保留 190 份，保存时间约为六个月以上，到期自动删除旧轮转记录；API 运行日志按时间或容量轮转。已解决的支持邮件和附件会在最后一次往来后 12 个月内复核并删除。因适用法律、争议处理或安全事件确有必要时，相关记录可能在必要范围内延长保存。").textSelection(.enabled)
                }
                Section("你的选择") { Text("你可以通过系统设置管理权限，也可以在本页撤回隐私同意。撤回后，App 不再启动由 CragPal 发起的相机、定位和联网处理，除非你再次同意。你还可以通过客服邮箱请求了解、更正或删除你向我们提供的信息；依法必须保留的记录会在法定期限届满后处理。发送邮件时请勿附带不必要的个人信息。政策更新会通过 App 或公开页面提供；涉及处理方式变化时，我们会按适用要求说明并取得必要同意。").textSelection(.enabled) }
            }
            .navigationTitle("隐私政策与支持")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
            .confirmationDialog(
                "撤回隐私同意？",
                isPresented: $showsRevokeConfirmation,
                titleVisibility: .visible
            ) {
                Button("确认撤回并停止使用", role: .destructive) {
                    privacyConsentVersion = 0
                    dismiss()
                }
                Button("取消", role: .cancel) {}
            } message: {
                Text("App 将返回隐私同意页。再次同意前不会请求相机、定位或下载岩场数据。")
            }
        }
    }
}
