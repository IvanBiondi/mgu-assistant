"""Offline display-language regressions: no vehicle or subprocess operations."""
import os
import unittest
from unittest.mock import patch
from i18n import tr, language, ZH_CN

class LocalizationTests(unittest.TestCase):
    def test_english_is_exact_fallback(self):
        with patch.dict(os.environ, {"MGU_UI_LANGUAGE": "en"}):
            for source in ZH_CN:
                self.assertEqual(tr(source), source)

    def test_chinese_and_unknown_values(self):
        with patch.dict(os.environ, {"MGU_UI_LANGUAGE": "zh-CN"}):
            self.assertEqual(tr("Activity log"), "操作日志")
            for value in ("--yes", "id8-bcp", "stock", "WBA00000000000000", "id -u = 0"):
                self.assertEqual(tr(value), value)
            self.assertEqual(language(), "zh-CN")

    def test_unsupported_locale_falls_back(self):
        with patch.dict(os.environ, {"MGU_UI_LANGUAGE": "de-DE"}):
            self.assertEqual(tr("Activity log"), "Activity log")

    def test_simplified_system_locale(self):
        with patch.dict(os.environ, {}, clear=True), patch("i18n.locale.getlocale", return_value=("zh_CN", "UTF-8")):
            self.assertEqual(language(), "zh-CN")

if __name__ == "__main__":
    unittest.main()
