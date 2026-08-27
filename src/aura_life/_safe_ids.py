"""Validation for persona ids that are about to become filesystem paths.

A persona id is caller-supplied data. Several places in this library turn one
straight into a path — ``<data_dir>/<persona_id>/profile.db`` and
``<db_dir>/<persona_id>_emotions.db`` — and SQLite will happily create or open
whatever those resolve to. Without a check, ``persona_id="../../../evil"``
escapes ``data_dir`` in both directions: it *creates* directories on write
(``ProfileDatabase.__init__`` calls ``parent.mkdir(parents=True)``) and *reads*
another persona's ``owner_device_id`` — the multi-user isolation key — on load.

This module is the single gate. Two rules:

1. **Reject, never strip.** Sanitizing by deleting ``..`` and separators is how
   traversal bugs come back: ``....//`` strips to ``../``, and a stripped id
   silently points at a *different* persona than the caller named. An id that
   is not well-formed is a bug or an attack, and either way the caller must
   hear about it. :func:`safe_persona_id` raises ``ValueError``.

2. **Prove containment after joining anyway.** :func:`safe_join` re-checks the
   resolved path against the resolved base directory, so a future caller that
   forgets rule 1, or a symlink planted inside ``data_dir``, still cannot land
   outside it.

Ids in this codebase are generated lowercase and separator-free
(``profile_db.py`` builds them as ``name.lower().replace(" ", "_")``), so the
accepted charset below is what real ids already look like.
"""

import re
from pathlib import Path
from typing import Union

__all__ = ["PERSONA_ID_PATTERN", "safe_persona_id", "safe_join"]

#: The only shape a persona id may have. Lower-case ASCII letters, digits,
#: underscore and hyphen; 1–64 characters.
#:
#: This charset is what makes the id path-safe, by construction rather than by
#: enumeration of attacks: it contains no ``/``, no ``\``, no ``.`` (so ``..``
#: and trailing-dot names are impossible), no ``:`` (so ``C:`` and NTFS
#: alternate data streams are impossible), no NUL, and no whitespace — and
#: since it cannot be empty, it cannot be a leading separator either.
PERSONA_ID_PATTERN = r"[a-z0-9_-]{1,64}"

_PERSONA_ID_RE = re.compile(PERSONA_ID_PATTERN)


def safe_persona_id(pid: str) -> str:
    """Return *pid* normalized to lower case, or raise.

    Args:
        pid: The caller-supplied persona id.

    Returns:
        ``pid.lower()`` — the form used for the on-disk directory and file
        names — once it has been proven to match :data:`PERSONA_ID_PATTERN`.

    Raises:
        ValueError: if *pid* is not a ``str``, or does not match the pattern.
            Nothing is stripped or repaired: a malformed id is refused.
    """
    if not isinstance(pid, str):
        raise ValueError(
            f"persona_id must be a str, got {type(pid).__name__}"
        )
    lowered = pid.lower()
    if not _PERSONA_ID_RE.fullmatch(lowered):
        raise ValueError(
            f"unsafe persona_id {pid!r}: must match {PERSONA_ID_PATTERN} "
            "(lower-case letters, digits, '_' and '-'; 1-64 chars). "
            "Path separators, '..', drive letters and absolute paths are refused."
        )
    return lowered


def safe_join(base_dir: Union[str, Path], *parts: str) -> Path:
    """Join *parts* under *base_dir* and prove the result stayed inside it.

    The belt to :func:`safe_persona_id`'s braces. Call it even when every part
    is already validated — it costs one ``resolve()`` and it is what catches a
    symlink inside ``base_dir``, or a future caller who joins an id this module
    never saw.

    Args:
        base_dir: Directory the result must remain within.
        *parts: Path components to append.

    Returns:
        The resolved, absolute path.

    Raises:
        ValueError: if the resolved path is not inside the resolved *base_dir*.
    """
    base = Path(base_dir).resolve()
    candidate = base.joinpath(*parts).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError(
            f"path {candidate} escapes its base directory {base}"
        )
    return candidate
