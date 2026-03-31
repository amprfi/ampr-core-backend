"""
Utilities for formatting message content across different channels.
"""

import re
import html


def markdown_to_telegram_html(text: str) -> str:
    """
    Convert Markdown to the HTML subset supported by Telegram's Bot API.

    Supported conversions:
        - Fenced code blocks (```lang ... ```) → <pre><code>
        - Inline code (`code`) → <code>
        - Bold (**text** / __text__) → <b>
        - Italic (*text* / _text_) → <i>
        - Strikethrough (~~text~~) → <s>
        - Links [text](url) → <a href="url">
        - Headers (# … ######) → <b>

    All other text is HTML-escaped so bare <, >, & won't break parsing.
    """
    # -- 1. Extract fenced code blocks before escaping -------------------
    code_blocks: list[str] = []

    def _store_code_block(match: re.Match) -> str:
        lang = match.group(1) or ""
        code = html.escape(match.group(2))
        placeholder = f"\x00CB{len(code_blocks)}\x00"
        if lang:
            code_blocks.append(
                f'<pre><code class="language-{lang}">{code}</code></pre>'
            )
        else:
            code_blocks.append(f"<pre>{code}</pre>")
        return placeholder

    text = re.sub(r"```(\w*)\n(.*?)```", _store_code_block, text, flags=re.DOTALL)

    # -- 2. Extract inline code -----------------------------------------
    inline_codes: list[str] = []

    def _store_inline_code(match: re.Match) -> str:
        code = html.escape(match.group(1))
        placeholder = f"\x00IC{len(inline_codes)}\x00"
        inline_codes.append(f"<code>{code}</code>")
        return placeholder

    text = re.sub(r"`([^`]+)`", _store_inline_code, text)

    # -- 3. Escape HTML entities in remaining text -----------------------
    text = html.escape(text)

    # -- 4. Markdown → HTML conversions ----------------------------------
    # Bold: **text** or __text__  (must come before italic)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    # Italic: *text* or _text_
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<i>\1</i>", text)
    # Strikethrough: ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    # Links: [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    # Headers: # Title → bold
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # -- 5. Restore protected spans -------------------------------------
    for i, block in enumerate(code_blocks):
        text = text.replace(f"\x00CB{i}\x00", block)
    for i, code in enumerate(inline_codes):
        text = text.replace(f"\x00IC{i}\x00", code)

    return text


def strip_markdown(text: str) -> str:
    """
    Remove Markdown formatting symbols from text for plain-text channels (e.g. SMS).

    Strips bold, italic, inline code, and heading markers while preserving
    the underlying text content.
    """
    # Bold: **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    # Italic: *text* or _text_
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'\1', text)
    # Inline code: `text`
    text = re.sub(r'`(.+?)`', r'\1', text)
    # Headings: ### text
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    return text
