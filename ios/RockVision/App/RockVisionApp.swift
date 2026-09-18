import SwiftUI

@main
struct RockVisionApp: App {
    @AppStorage(PrivacyConsent.storageKey) private var privacyConsentVersion = 0

    var body: some Scene {
        WindowGroup {
            if PrivacyConsent.isGranted(version: privacyConsentVersion) {
                ContentView()
            } else {
                PrivacyConsentGate(consentVersion: $privacyConsentVersion)
            }
        }
    }
}
