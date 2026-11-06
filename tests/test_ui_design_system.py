from pathlib import Path
import unittest

import app as application


ROOT = Path(__file__).resolve().parents[1]


class UIDesignSystemTests(unittest.TestCase):
    def test_clean_dark_premium_tokens_and_reduced_motion_are_defined(self):
        css = (ROOT / "static" / "css" / "design-system.css").read_text(encoding="utf-8")
        for token in ("#0F1115", "#181B20", "#2A2F38", "#F1F5F9", "#60A5FA"):
            self.assertIn(token, css)
        self.assertIn("font-family: Inter", css)
        self.assertIn("prefers-reduced-motion: reduce", css)
        self.assertIn(".lucide", css)
        self.assertNotIn("transition: all", css)

    def test_ui_runtime_exposes_loading_search_modal_and_toast_behaviors(self):
        script = (ROOT / "static" / "js" / "ui-system.js").read_text(encoding="utf-8")
        for behavior in (
            "initClearableSearches",
            "setButtonLoading",
            "showToast",
            "showConfirm",
            "handleModalKeys",
        ):
            self.assertIn(behavior, script)
        self.assertIn("aria-busy", script)
        self.assertIn("event.key === 'Escape'", script)

    def test_shared_layout_loads_design_system_and_accessible_feedback(self):
        layout = (ROOT / "templates" / "layout.html").read_text(encoding="utf-8")
        self.assertIn("css/design-system.css", layout)
        self.assertIn("js/ui-system.js", layout)
        self.assertIn('aria-live="polite"', layout)
        self.assertIn('aria-modal="true"', layout)
        self.assertIn('aria-describedby="app-confirm-text"', layout)
        self.assertIn('aria-current="page"', layout)
        self.assertIn("from \"_icons.html\" import icon", layout)

    def test_search_and_crm_use_real_reusable_interactions(self):
        search = (ROOT / "templates" / "search.html").read_text(encoding="utf-8")
        crm = (ROOT / "templates" / "crm.html").read_text(encoding="utf-8")
        self.assertIn("GestaoLeadUI.setButtonLoading", search)
        self.assertIn('id="city_autocomplete_input" data-clearable', search)
        self.assertIn('id="filter_nome" data-clearable', crm)
        self.assertIn("ui-empty-state", crm)

    def test_login_uses_same_design_system(self):
        client = application.app.test_client()
        response = client.get("/login")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("/static/css/design-system.css", html)
        self.assertIn("/static/js/ui-system.js", html)
        self.assertIn("Inter", html)

    def test_third_party_notice_records_uiverse_license_boundary(self):
        notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertIn("Uiverse", notice)
        self.assertIn("MIT", notice)
        self.assertIn("Lucide", notice)
        self.assertIn("ISC", notice)
        self.assertIn("Nenhum componente Pro", notice)


if __name__ == "__main__":
    unittest.main()
