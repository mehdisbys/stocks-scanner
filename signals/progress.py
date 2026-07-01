"""Tiny zero-dependency progress indicator.

``track(items, desc=..., label=...)`` yields the items unchanged while showing
progress on stderr. Behaviour:

* if ``tqdm`` is installed, use it (nice bar);
* else if stderr is a real terminal, print a self-overwriting
  ``desc i/total LABEL`` counter;
* else (piped/redirected) stay completely silent.

So it's helpful interactively and invisible in logs, with no required deps.
"""

from __future__ import annotations

import sys
from typing import Callable, Iterable, Optional


def track(items: Iterable, total: Optional[int] = None, desc: str = "scanning",
          label: Optional[Callable[[object], str]] = None, stream=None):
    stream = stream or sys.stderr
    items = list(items)
    if total is None:
        total = len(items)

    # Preferred: real progress bar if tqdm is available.
    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None
    if tqdm is not None:
        bar = tqdm(items, total=total, desc=desc, unit="sym", leave=False)
        for it in bar:
            if label:
                bar.set_postfix_str(label(it))
            yield it
        return

    # Fallback: lightweight counter, only when attached to a terminal.
    show = bool(getattr(stream, "isatty", lambda: False)())
    width = 56
    for i, it in enumerate(items, 1):
        if show:
            lab = f" {label(it)}" if label else ""
            stream.write(("\r%s %d/%d%s" % (desc, i, total, lab))[:width].ljust(width))
            stream.flush()
        yield it
    if show:
        stream.write("\r".ljust(width) + "\r")  # clear the line
        stream.flush()
