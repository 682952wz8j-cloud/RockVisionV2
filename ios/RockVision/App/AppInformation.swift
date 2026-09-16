import SwiftUI

/// Available offline, including when location or network access is unavailable.
struct AppInformationView: View {
    @Environment(\.dismiss) private var dismiss
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
                Section("运营者与联系") { Text("CragPal 由北京榫卯管理咨询有限公司运营。隐私问题和技术支持请联系 z.zhang020@gmail.com。更新日期：2026 年 9 月 16 日。").textSelection(.enabled) }
                Section("相机与位置") { Text("相机画面用于在设备上识别岩壁、计算视觉定位并显示路线；本版不会将相机图像或视频上传至我们的服务器。位置仅在设备上用于选择附近已支持的岩场，不上传至我们的服务器，也不参与精确视觉定位。你可以在系统设置中关闭相机或定位权限；关闭后相应功能将无法使用。").textSelection(.enabled) }
                Section("网络与本地存储") { Text("App 通过网络下载岩场目录和路线数据。提供服务的服务器及云服务商会接收 IP 地址、请求时间和资源路径等必要网络信息，用于交付内容、保障服务和排查故障。我们不将这些信息用于广告追踪。本地会保存下载的岩场包和故障诊断信息。卸载 App 可移除该 App 的本地数据，之后重新安装需要重新下载。").textSelection(.enabled) }
                Section("共享与保存") { Text("本版没有广告、账户注册或订阅购买功能。我们不出售个人信息，仅向提供托管和数据传输服务所必需的服务商提供必要信息，或在法律要求时披露。服务日志和支持邮件仅在提供服务、处理问题及履行法定义务所必需的期限内保留，之后删除或匿名化。").textSelection(.enabled) }
                Section("你的选择") { Text("你可以通过系统设置管理权限，也可以通过客服邮箱请求了解、更正或删除你向我们提供的信息。发送邮件时，请勿附带不必要的个人信息；我们只为处理你的请求使用邮件内容和联系方式。政策更新会随 App 或公开页面发布。").textSelection(.enabled) }
            }
            .navigationTitle("隐私政策与支持")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
        }
    }
}
