"""Small SDL2 fixes applied to the pinned Android bootstrap before compilation."""

from pathlib import Path


EMPTY_EDITOR_DELETE = r'''
    // The native editor can be empty while Kivy still owns text after refocus.
    private boolean deleteFromEmptyEditor(int beforeLength, int afterLength) {
        Editable editable = getEditable();
        if (beforeLength <= 0 || afterLength != 0 || editable == null
                || editable.length() != 0 || !mCommittedText.isEmpty()) {
            return false;
        }
        while (beforeLength-- > 0) {
            nativeGenerateScancodeForUnichar('\b');
        }
        return true;
    }

'''

CODEPOINT_DELETE = '''
    @Override
    public boolean deleteSurroundingTextInCodePoints(int beforeLength, int afterLength) {
        if (deleteFromEmptyEditor(beforeLength, afterLength)) return true;
        boolean handled = super.deleteSurroundingTextInCodePoints(beforeLength, afterLength);
        if (handled) updateText();
        return handled;
    }

'''


def patch_sdl_keyboard(source):
    if "private boolean deleteFromEmptyEditor(" in source:
        return source
    method = "    @Override\n    public boolean deleteSurroundingText(int beforeLength, int afterLength) {"
    insertion = "        if (!super.deleteSurroundingText(beforeLength, afterLength)) {"
    update = "    protected void updateText() {"
    for anchor in (method, insertion, update):
        if source.count(anchor) != 1:
            raise RuntimeError("Pinned SDL2 keyboard source changed; review the backspace fix before building")
    source = source.replace(method, EMPTY_EDITOR_DELETE + method)
    source = source.replace(insertion, "        if (deleteFromEmptyEditor(beforeLength, afterLength)) return true;\n" + insertion)
    return source.replace(update, CODEPOINT_DELETE + update)


def before_apk_assemble(toolchain):
    candidates = list(Path(toolchain._dist.dist_dir).glob("src/**/org/libsdl/app/SDLActivity.java"))
    if len(candidates) != 1:
        raise RuntimeError("Expected one SDLActivity.java in the Android distribution")
    path = candidates[0]
    source = path.read_text(encoding="utf-8")
    patched = patch_sdl_keyboard(source)
    if source != patched:
        path.write_text(patched, encoding="utf-8")
