#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Check RST inline markup (``bold``, ``literal``) adjacent to non-boundary
chars (CJK / full-width brackets). Uses docutils' real regex char classes.
Temporary helper; safe to delete."""
import os
import re
from docutils.utils.punctuation_chars import openers, closers, delimiters
from docutils.utils.punctuation_chars import closing_delimiters

ROOT = "/Users/taochengwei/Code/passportd"
FILES = []
for base, _dirs, names in os.walk(os.path.join(ROOT, "docs")):
    for n in names:
        if n.endswith(".rst"):
            FILES.append(os.path.join(base, n))
FILES.append(os.path.join(ROOT, "CHANGELOG.rst"))

START_OK = re.compile(r"(?:\s|[%s%s])$" % (openers, delimiters))
END_OK = re.compile(r"(?:\s|[%s%s%s])$" % (closing_delimiters, delimiters, closers))
MARKERS = [("BOLD", r"\*\*"), ("LIT", r"``")]

for path in FILES:
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    for i, line in enumerate(lines, 1):
        stripped = line.rstrip("\n")
        for tag, pat in MARKERS:
            positions = [m.start() for m in re.finditer(pat, stripped)]
            if not positions:
                continue
            if len(positions) % 2:
                print("ODD[%s]:" % tag, os.path.relpath(path, ROOT), i,
                      repr(stripped[:130]))
                continue
            for j in range(0, len(positions), 2):
                start_pos, end_pos = positions[j], positions[j + 1]
                plen = 2  # actual marker length
                before = stripped[start_pos - 1] if start_pos > 0 else None
                after = stripped[end_pos + plen] if end_pos + plen < len(stripped) else None
                problems = []
                if before is not None and not START_OK.match(before):
                    problems.append("before %r" % before)
                if after is not None and not END_OK.match(after):
                    problems.append("after %r" % after)
                if problems:
                    print("FIX[%s]:" % tag, os.path.relpath(path, ROOT), i,
                          "|", "; ".join(problems), "|", repr(stripped[:140]))
