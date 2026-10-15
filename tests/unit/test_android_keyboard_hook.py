import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location("android_hooks", Path(__file__).parents[2] / "assets/packaging/android/hooks.py")
hooks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hooks)


def test_hook_is_idempotent_and_preserves_normal_sdl_deletion():
    source = """    @Override
    public boolean deleteSurroundingText(int beforeLength, int afterLength) {
        if (!super.deleteSurroundingText(beforeLength, afterLength)) {
            return false;
        }
        updateText();
        return true;
    }
    protected void updateText() {
    }
"""
    patched = hooks.patch_sdl_keyboard(source)
    assert hooks.patch_sdl_keyboard(patched) == patched
    assert "super.deleteSurroundingText(beforeLength, afterLength)" in patched
    assert "super.deleteSurroundingTextInCodePoints(beforeLength, afterLength)" in patched
    assert "editable.length() != 0 || !mCommittedText.isEmpty()" in patched
    assert "beforeLength != 1" in patched


def test_hook_refuses_changed_sdl_source():
    with pytest.raises(RuntimeError, match="Pinned SDL2"):
        hooks.patch_sdl_keyboard("unexpected source")
