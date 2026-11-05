import locale

import pytest

from carveracontroller import translation


@pytest.mark.parametrize(
    "saved_language,expected", [(None, "en"), ("", "en"), ("unsupported", "en"), ("en", "en"), ("zh-CN", "zh-CN")]
)
def test_english_default_preserves_supported_saved_language(saved_language, expected, monkeypatch):
    monkeypatch.setattr(locale, "getdefaultlocale", lambda: ("zh_CN", "UTF-8"))
    original = translation._translator
    try:
        translation.init(saved_language)
        assert translation.tr.lang == expected
    finally:
        translation._translator = original
        original.switch_lang(original.lang)
