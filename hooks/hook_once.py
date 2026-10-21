"""Once-per-key markers shared by the hooks that say each thing once.

Not a hook: it carries no `# claude-hook:` marker, so the registrars skip it.
The hooks load it by path (hooks run from an arbitrary cwd, with no sys.path to
find a sibling). Stdlib only, like the hooks that load it.
"""

import hashlib
import os
import tempfile
from pathlib import Path


def stamp_dir(name: str) -> Path:
    """Where a hook's markers live, namespaced per user.

    On POSIX the temp directory is shared, so an unnamespaced directory created
    by another user is not writable by this one -- and a guard that cannot
    write its marker re-fires on every call. Windows %TEMP% is already
    per-user and has no getuid, so the suffix is omitted there.
    """
    getuid = getattr(os, "getuid", None)
    suffix = f"-{getuid()}" if getuid else ""
    return Path(tempfile.gettempdir()) / f"{name}{suffix}"


def claim(name: str, key: str) -> bool:
    """True if `key` was not yet claimed (now it is), False if it already was.

    Best effort by design: a filesystem error returns True, so the caller
    fires. A repeat is cheaper than a missed message. O_EXCL makes test and
    claim one step; an exists()-then-touch pair double-fires when two calls
    race, which is the burst these guards exist to collapse.
    """
    directory = stamp_dir(name)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        os.close(
            os.open(
                directory / hashlib.sha256(key.encode()).hexdigest()[:16],
                os.O_CREAT | os.O_EXCL,
            )
        )
    except FileExistsError:
        return False
    except OSError:
        return True
    return True
