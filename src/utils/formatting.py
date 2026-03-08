"""
Utilities for formatting message content across different channels.
"""

import re


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
