# -*- coding: utf-8 -*-
"""临时校验脚本：检查 setup.rst / CHANGELOG.rst 解析错误与标题下划线长度。"""
import io
import docutils.core as dc

files = ["docs/guide/setup.rst", "CHANGELOG.rst",
         "docs/guide/usage.rst", "docs/guide/install.rst",
         "docs/guide/quickstart.rst", "docs/index.rst"]

# 1) docutils 完整解析
for p in files:
    with open(p, encoding="utf-8") as f:
        src = f.read()
    err = io.StringIO()
    dc.publish_string(src, source_path=p, writer_name="html5",
                      settings_overrides={"warning_stream": err})
    out = err.getvalue()
    errs = [l for l in out.splitlines()
            if "ERROR" in l or "too short" in l or "start-string" in l or "unindent" in l]
    print(p, "->", errs if errs else "OK")


def width(s):
    """docutils 视角的标题宽度：CJK/全角算 2，其余算 1。"""
    return sum(2 if c >= "\u4e00" and c <= "\u9fff" else 1 for c in s)


# 2) 标题下划线长度扫描
for p in files:
    with open(p, encoding="utf-8") as f:
        lines = f.read().splitlines()
    bad = []
    for i in range(len(lines) - 1):
        t, u = lines[i], lines[i + 1]
        if not t.strip() or not u:
            continue
        if len(u.strip()) < 2 or u != u.strip():
            continue
        if not all(c in "=-~" for c in u):
            continue
        w = width(t)
        if len(u) < w:
            bad.append((i + 1, t, len(u), w))
    print(p, "bad titles:", bad if bad else "none")
