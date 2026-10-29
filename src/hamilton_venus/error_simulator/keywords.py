"""Port of the ``ErrorSimulator`` HSL ``_GenerateKeywords`` submethod.

Turns a plain-language module / step / error description into the list of
upper-case keyword tokens the knowledge-base cascade matches against
``KEY1..KEY3`` / ``TAG1`` / ``TAG2``. The transformation is a faithful port: the
same punctuation stripping, stop-word removal and (order-sensitive) domain
synonym rewrites the HSL applies, so a phrase keywords the same way here as it
does in VENUS.
"""

from __future__ import annotations

#: Characters deleted outright (HSL: replaced with "").
_STRIP_CHARS = ["'", '"', "\n", "(", ")", ".", "-", "_", ",", ";", ":"]

#: Tokens replaced with a single space. The surrounding spaces are part of the
#: match, exactly as in the HSL, so only whole words between spaces are removed.
_STOPWORDS = [
    "\t",
    " THE ",
    " ON ",
    " A ",
    " AT ",
    " AN ",
    " OF ",
    " OR ",
    " IS ",
    " AND ",
    " TO ",
    " ARE ",
    " ITS ",
    " FOR ",
    " BE ",
    " NOT ",
]

#: Domain synonym rewrites, applied in order (each a sequential ``str.replace``);
#: order matters -- e.g. ``" DRIVE"`` before ``"DRIVE"``.
_SYNONYMS: list[tuple[str, str]] = [
    ("INITIALIZATION", "INITIALIZE"),
    ("ASPIRATED", "ASPIRATE"),
    ("ASPIRATION", "ASPIRATE"),
    ("DISPENSED", "DISPENSE"),
    ("DISPENSATION", "DISPENSE"),
    ("D DRIVE", "DISPENSE"),
    (" D ", "DISPENSE"),
    ("PUSH", "PULL"),
    ("PICKUP", "PICK"),
    ("CORRECTLY", "CORRECT"),
    ("DROPLET", "DROP"),
    ("CONTROLLING", "CONTROL"),
    ("ANTIDROP", "ADC"),
    ("ANTI DROP", "ADC"),
    (" LOSS ", " LOST "),
    ("CHECK SUM", "CHECKSUM"),
    ("MAXIMUM", "MAX"),
    ("MINIMUM", "MIN"),
    ("LOAD TRAY", "LOADTRAY"),
    ("LOADING", "LOAD"),
    ("VOLTAGES", "VOLTAGE"),
    ("IDENTIFICATION", "ID"),
    ("WOI", "WINDOW INTEREST"),
    ("ROI", "WINDOW INTEREST"),
    ("I/O", "IO"),
    (" DRIVE", ""),
    ("DRIVE", ""),
    ("PROGRAMABLE", "PROGRAMMABLE"),
    ("WRITEABLE", "WRITABLE"),
    ("OUTSIDE", "OUT"),
    ("2ND", "SECOND"),
    ("PARAMETERS", "PARAMETER"),
    ("RECEIVING", "RECEIVE"),
    ("RETRIES", "RETRY"),
    ("AUTO LOAD", "AUTOLOAD"),
]


def generate_keywords(text: str) -> list[str]:
    """Return the upper-case keyword tokens for *text*.

    Mirrors HSL ``_GenerateKeywords``: upper-case, strip punctuation, drop
    stop-words, apply synonym rewrites, then split on single spaces. Empty
    tokens (from runs of spaces or leading/trailing space, as the HSL produces)
    are dropped -- they never match a populated ``KEY`` column anyway.
    """
    work = (text or "").upper()
    for char in _STRIP_CHARS:
        work = work.replace(char, "")
    for token in _STOPWORDS:
        work = work.replace(token, " ")
    for src, dst in _SYNONYMS:
        work = work.replace(src, dst)
    return [token for token in work.split(" ") if token]


def keyword_sql_list(text: str) -> str:
    """The keywords of *text* rendered as an SQL ``IN`` list body, e.g.
    ``"'FOO','BAR'"`` -- kept for parity with the HSL query strings / tracing."""
    return ",".join(f"'{token}'" for token in generate_keywords(text))
