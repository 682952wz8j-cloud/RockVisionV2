from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ProductionEdgeTests(unittest.TestCase):
    def test_nginx_http_config_proxies_hostname_and_keeps_ip_default(self) -> None:
        conf = (ROOT / "deploy" / "nginx" / "api.cragpal.com.conf").read_text(encoding="utf-8")
        self.assertIn("server_name api.cragpal.com;", conf)
        self.assertIn("listen 80 default_server;", conf)
        self.assertIn("proxy_pass http://cragpal_api;", conf)
        self.assertIn("server 127.0.0.1:8000;", conf)
        self.assertIn("location /.well-known/acme-challenge/", conf)
        self.assertNotIn("ssl_certificate", conf)

    def test_nginx_tls_template_is_hostname_443_only(self) -> None:
        conf = (ROOT / "deploy" / "nginx" / "api.cragpal.com.ssl.conf.template").read_text(encoding="utf-8")
        self.assertIn("listen 443 ssl;", conf)
        self.assertIn("server_name api.cragpal.com;", conf)
        self.assertIn("proxy_pass http://cragpal_api;", conf)
        self.assertIn("/etc/letsencrypt/live/api.cragpal.com/fullchain.pem", conf)
        self.assertIn("X-Forwarded-Proto https;", conf)

    def test_release_ios_base_url_is_production_hostname(self) -> None:
        source = (ROOT / "ios" / "RockVision" / "Features" / "Cloud" / "CloudAPIConfiguration.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn('static let productionHTTPSURL = URL(string: "https://api.cragpal.com")!', source)
        self.assertIn("static let `default` = CloudAPIConfiguration.production", source)
        self.assertIn("static let `default` = CloudAPIConfiguration.development", source)
        release_default = source.rsplit("#else", 1)[1].rsplit("#endif", 1)[0]
        self.assertIn("CloudAPIConfiguration.production", release_default)
        self.assertNotIn("developmentTemporaryHTTP", release_default)
        self.assertNotIn("124.223.178.91", release_default)
        self.assertNotIn("JinshidongLocalTest", release_default)

    def test_field_engineering_hud_is_generic_and_package_driven(self) -> None:
        hud = (ROOT / "ios" / "RockVision" / "Features" / "DebugOverlay" / "Stage5DebugHUD.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn("ProductionRouteFieldCopy", hud)
        self.assertIn("officialText", hud)
        self.assertIn("quickdrawLine", hud)
        self.assertNotIn("wall_jinshidong_01", hud)
        self.assertNotIn("wall_jiulongfeng_01", hud)
        self.assertNotIn("jinshidong_lucky_baby", hud)
        self.assertNotIn("jiulongfeng_bai_qiang_ce_shi", hud)
        processor = (ROOT / "ios" / "RockVision" / "Features" / "OpenCV" / "OpenCVFrameProcessor.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn("makePackageRoutePlan", processor)
        self.assertIn("productionFieldRoutes", processor)
        self.assertIn("clearProductionCloudRelease", processor)
        self.assertNotIn("makeJinshidongLocalTestRoutePlan", processor)
        plan = (ROOT / "ios" / "RockVision" / "Features" / "PnP" / "RouteRenderPlan.swift").read_text(encoding="utf-8")
        self.assertIn("package_routes", plan)
        self.assertNotIn("jinshidong_local_test", plan)
        runtime = (ROOT / "ios" / "RockVision" / "Features" / "Cloud" / "ProductionRuntime.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn("clearProductionCloudRelease", runtime)
        self.assertIn("WallCandidateSelector.selectWallId", runtime)
        self.assertNotIn("wall_jinshidong_01", runtime)
        self.assertNotIn("wall_jiulongfeng_01", runtime)

    def test_enable_https_script_uses_webroot_and_hostname(self) -> None:
        script = (ROOT / "deploy" / "nginx" / "enable-https.sh").read_text(encoding="utf-8")
        self.assertIn("DOMAIN=api.cragpal.com", script)
        self.assertIn("certbot certonly --webroot", script)
        self.assertIn("-w /var/www/certbot", script)
        self.assertIn("-d \"${DOMAIN}\"", script)
        self.assertIn("api.cragpal.com.ssl.conf.template", script)
        self.assertIn("systemctl reload nginx", script)
