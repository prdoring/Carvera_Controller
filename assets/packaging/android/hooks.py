"""Small SDL2 fixes applied to the pinned Android bootstrap before compilation."""

from pathlib import Path


EMPTY_EDITOR_DELETE = r'''
    // The native editor can be empty while Kivy still owns text after refocus.
    private boolean deleteFromEmptyEditor(int beforeLength, int afterLength) {
        Editable editable = getEditable();
        if (beforeLength != 1 || afterLength != 0 || editable == null
                || editable.length() != 0 || !mCommittedText.isEmpty()) {
            return false;
        }
        nativeGenerateScancodeForUnichar('\b');
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
    method = "    @Override\n    public boolean deleteSurroundingText(int beforeLength, int afterLength) {"
    if "private boolean deleteFromEmptyEditor(" in source:
        if EMPTY_EDITOR_DELETE.strip() in source:
            return source
        start = source.index("    // The native editor can be empty")
        end = source.index(method, start)
        previous = source[start:end]
        if "beforeLength <= 0" not in previous or "while (beforeLength-- > 0)" not in previous:
            raise RuntimeError("Unexpected SDL2 empty-editor deletion fix; review before building")
        return source[:start] + EMPTY_EDITOR_DELETE.lstrip("\n") + source[end:]
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
