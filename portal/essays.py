"""Essay versions, inline comment anchoring, highlighting and version comparison."""
import difflib
import re

from django.db import transaction
from django.utils.html import escape
from django.utils.safestring import mark_safe

from .models import EssayComment, EssayVersion

MAX_QUOTE = 500


def normalize(text):
    """Browsers submit \r\n; store \n so character offsets match what the reader sees."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


@transaction.atomic
def save_version(essay, body, by, *, base_number=None, note=""):
    """Save `body` as a new version. Returns (version, created, conflict).

    - Unchanged text creates nothing.
    - `conflict` is True when someone else saved a newer version after the editor
      opened the page (base_number). The new text is still saved; nothing is lost.
    """
    body = normalize(body)
    latest = essay.versions.select_for_update().order_by("-number").first()
    if latest is not None and latest.body == body:
        return latest, False, False
    conflict = latest is not None and base_number is not None and latest.number != base_number
    version = EssayVersion.objects.create(
        essay=essay, number=(latest.number + 1) if latest else 1, body=body, note=note[:120], created_by=by
    )
    essay.save(update_fields=["updated_at"])
    return version, True, conflict


def restore_version(essay, old_version, by):
    return save_version(essay, old_version.body, by, note=f"Restored from version {old_version.number}")


def add_comment(version, by, body, *, start=None, end=None, quote=""):
    """Create a comment. Anchors to the selected passage when the offsets match the text;
    otherwise falls back to the first occurrence of the quote, or no anchor."""
    text = version.body or ""
    quote = normalize(quote)[:MAX_QUOTE]
    anchored = (
        start is not None and end is not None and 0 <= start < end <= len(text) and text[start:end] == quote
    )
    if not anchored and quote:
        found = text.find(quote)
        if found >= 0:
            start, end, anchored = found, found + len(quote), True
    if not anchored:
        start = end = None
    return EssayComment.objects.create(version=version, author=by, body=body.strip(), start=start, end=end, quote=quote)


def highlight(body, comments):
    """Return the essay as safe HTML with <mark> around commented passages."""
    body = body or ""
    ranges = [(c.start, c.end, c.pk) for c in comments if c.is_anchored and c.end <= len(body)]
    if not ranges:
        return escape(body)
    cuts = sorted({0, len(body), *[r[0] for r in ranges], *[r[1] for r in ranges]})
    out = []
    for a, b in zip(cuts, cuts[1:]):
        piece = escape(body[a:b])
        covering = [pk for (s, e, pk) in ranges if s <= a and b <= e]
        if covering:
            ids = " ".join(f"c{pk}" for pk in covering)
            out.append(f'<mark data-comments="{ids}" id="m{covering[0]}-{a}">{piece}</mark>')
        else:
            out.append(piece)
    return mark_safe("".join(out))


_TOKEN = re.compile(r"\s+|[^\s]+")


def compare(old, new):
    """Word-level comparison as safe HTML: <del> for removed text, <ins> for added text."""
    a, b = _TOKEN.findall(old or ""), _TOKEN.findall(new or "")
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(escape("".join(a[i1:i2])))
        if op in ("delete", "replace"):
            out.append(f"<del>{escape(''.join(a[i1:i2]))}</del>")
        if op in ("insert", "replace"):
            out.append(f"<ins>{escape(''.join(b[j1:j2]))}</ins>")
    return mark_safe("".join(out))
