"""
Tema completo do cliente: fonte, fundo, texto, cards, menu e cantos.

O que se fixa aqui são as GARANTIAS do tema, não o desenho: qualquer
combinação salva é legível, o menu nunca fica com texto da mesma cor, as
linhas dos gráficos aparecem no fundo escolhido e o tema sobrevive ao banco.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core import storage
from core.branding import brand_for_tenant, brand_palette, contrast_ratio, css_variables, style_variables
from core.tenant_theme import (
    DEFAULT_THEME,
    MIN_TEXT_CONTRAST,
    PRESETS,
    clean_theme,
    google_fonts_url,
    parse_theme,
    theme_tokens,
)

DARK = {"text_color": "#E8EAED", "background_color": "#0F1115", "surface_color": "#171A21",
        "sidebar_color": "#0B0D11"}


class ThemeRulesTests(unittest.TestCase):
    def test_missing_or_broken_theme_falls_back_to_default(self):
        self.assertEqual(parse_theme(None), DEFAULT_THEME)
        self.assertEqual(parse_theme("{json quebrado"), DEFAULT_THEME)
        theme = parse_theme({"text_color": "#12", "font_body": "comic-sans", "radius": "x", "extra": 1})
        self.assertEqual(theme, DEFAULT_THEME)

    def test_unreadable_text_is_refused_with_the_ratio(self):
        with self.assertRaises(ValueError) as error:
            clean_theme({"text_color": "#BBBBBB", "background_color": "#FFFFFF"})
        self.assertIn(":1", str(error.exception))

    def test_half_typed_colour_is_an_error_not_a_silent_default(self):
        with self.assertRaises(ValueError):
            clean_theme({"background_color": "#12AB"})

    def test_every_preset_is_readable(self):
        for key, preset in PRESETS.items():
            with self.subTest(preset=key):
                theme = clean_theme({k: v for k, v in preset.items() if k != "label"})
                self.assertGreaterEqual(contrast_ratio(theme["text_color"], theme["background_color"]),
                                        MIN_TEXT_CONTRAST)

    def test_sidebar_text_always_readable_on_the_sidebar(self):
        """Menu escuro com texto escuro escolhido para o resto do painel."""
        for preset in PRESETS.values():
            tokens = theme_tokens(preset)
            with self.subTest(sidebar=preset["sidebar_color"]):
                self.assertGreaterEqual(
                    contrast_ratio(tokens["--sidebar-ink"], tokens["--sidebar-bg"]), MIN_TEXT_CONTRAST
                )

    def test_dark_theme_switches_color_scheme_and_derives_tones(self):
        tokens = theme_tokens(DARK)
        self.assertEqual(tokens["color-scheme"], "dark")
        self.assertEqual(tokens["--ink"], "#E8EAED")
        # o tom secundário fica ENTRE o texto e o card, nunca preto
        self.assertLess(contrast_ratio(tokens["--ink-secondary"], DARK["surface_color"]),
                        contrast_ratio(tokens["--ink"], DARK["surface_color"]))
        self.assertGreater(contrast_ratio(tokens["--ink-secondary"], DARK["surface_color"]), 4.5)
        self.assertEqual(theme_tokens(DEFAULT_THEME)["color-scheme"], "light")

    def test_chart_series_stay_visible_on_a_dark_card(self):
        palette = brand_palette("#0B3D91", "#000000", DARK["surface_color"])
        for color in palette["series"]:
            with self.subTest(color=color):
                self.assertGreaterEqual(contrast_ratio(color, DARK["surface_color"]), 3.0)

    def test_fonts_are_loaded_only_when_needed(self):
        url = google_fonts_url({"font_body": "poppins", "font_heading": "playfair"})
        self.assertIn("Poppins", url)
        self.assertIn("Playfair+Display", url)
        self.assertIsNone(google_fonts_url({"font_body": "system", "font_heading": "system"}))

    def test_tokens_reach_inline_style_and_head(self):
        brand = {"primary_color": "#E5001A", "theme": {**DEFAULT_THEME, **DARK, "font_body": "poppins"}}
        inline = style_variables(brand)
        self.assertEqual(inline["colorScheme"], "dark")
        self.assertNotIn("color-scheme", inline)
        self.assertIn("Poppins", inline["--font"])
        self.assertIn("color-scheme:dark", css_variables(brand))
        # a cor de ação continua sendo a da marca, o tema não a sobrescreve
        self.assertEqual(inline["--brand"], "#E5001A")


class ThemeStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = storage.DB_PATH
        storage.DB_PATH = Path(self.temp_dir.name) / "pulse-test.db"
        storage.init_db()

    def tearDown(self):
        storage.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    def _create(self, **extra):
        return storage.create_tenant(
            name="Cliente Tema", slug="cliente-tema", owner_name="Gestor",
            owner_email="tema@teste.com", password="Senha@Teste1", **extra,
        )

    def _update(self, tenant, **extra):
        return storage.update_tenant_settings(
            tenant["id"], name=tenant["name"], primary_color=tenant["primary_color"],
            secondary_color=tenant["secondary_color"], logo_data=None, status="active",
            meta_ad_account_id=None, google_ads_customer_id=None, **extra,
        )

    def test_theme_round_trips_through_the_database(self):
        tenant = self._create(theme={**DARK, "font_body": "manrope", "radius": "reto"})
        theme = brand_for_tenant(tenant)["theme"]
        self.assertEqual(theme["surface_color"], "#171A21")
        self.assertEqual((theme["font_body"], theme["radius"]), ("manrope", "reto"))

    def test_saving_without_theme_keeps_the_current_one(self):
        tenant = self._create(theme=DARK)
        updated = self._update(tenant)
        self.assertEqual(parse_theme(updated["theme_data"])["background_color"], "#0F1115")

    def test_unreadable_theme_is_not_saved(self):
        tenant = self._create()
        with self.assertRaises(ValueError):
            self._update(tenant, theme={"text_color": "#FFFFFF", "background_color": "#F5F5F5"})
        self.assertEqual(parse_theme(storage.get_tenant(tenant["id"])["theme_data"]), DEFAULT_THEME)

    def test_client_login_carries_the_theme(self):
        self._create(theme=DARK)
        user = storage.authenticate("tema@teste.com", "Senha@Teste1")
        self.assertEqual(parse_theme(user["theme_data"])["text_color"], "#E8EAED")


if __name__ == "__main__":
    unittest.main()
