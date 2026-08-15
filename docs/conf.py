# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import sys

from pallets_sphinx_themes import get_version, ProjectLink

# 文档构建不需要真实数据库与缓存连接，强制使用 SQLite 内存库。
# postgresql / redis 驱动在文档构建环境可能未安装，且 autodoc 导入
# 模块时会触发 peewee 的 Field.bind() → get_binary_type() 调用。
# get_binary_type 定义在 PostgresqlDatabase 子类上，无法通过基类
# Database 的 monkey-patch 拦截，必须在导入前覆写环境变量。
os.environ["PASSPORT_DB_URI"] = "sqlite:///:memory:"
os.environ["PASSPORT_REDIS_URI"] = "redis://localhost:6379/0"

sys.path.insert(0, os.path.abspath("../"))

# autodoc 导入项目模块时 model.py 会执行模块级的：
#   with db.atomic():
#       db.create_tables([...])
# 这会尝试建立真实数据库连接。以下 patch 阻止数据库连接，
# 确保文档构建不依赖实际数据库或缓存服务。
import peewee as _peewee

_orig_atomic = _peewee.Database.atomic
_orig_connect = _peewee.Database.connect
_orig_create_tables = _peewee.Database.create_tables


def _fake_atomic(self):
    class _FakeCtx:
        def __enter__(_self):
            return _self

        def __exit__(_self, *_a):
            pass

    return _FakeCtx()


_peewee.Database.atomic = _fake_atomic
_peewee.Database.connect = lambda self, reuse_if_open=False: None
_peewee.Database.create_tables = lambda self, models, safe=True: None

# mock 外部依赖避免文档构建期间触发真实连接或网络请求
autodoc_mock_imports = [
    "redis",
    "flask_pluginkit",
    "authlib",
    "joserfc",
    "prometheus_client",
]

project = "passportd"
copyright = "2021-2026, Hiroshi.tao"
author = "Hiroshi.tao"
release, version = get_version(project)


# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",  # 支持Google风格docstring
    "pallets_sphinx_themes",
]

issues_github_path = "staugur/passportd"

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

language = "zh_CN"
source_suffix = ".rst"
master_doc = "index"

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "flask"
html_static_path = ["_static"]
html_theme_options = {"index_sidebar_logo": True}
html_context = {
    "project_links": [
        ProjectLink("PyPI releases", "https://pypi.org/project/passportd"),
        ProjectLink("Source Code", "https://github.com/staugur/passportd"),
        ProjectLink("Issue Tracker", "https://github.com/staugur/passportd/issues/"),
        ProjectLink("Official Document", "https://passportd.readthedocs.io/"),
    ]
}
html_static_path = ["_static"]
html_favicon = "_static/images/favicon.png"
html_show_sourcelink = False


# -- Strip LICENSE from module docstrings -----------------------------------

def _strip_license(app, what, name, obj, options, lines):
    """移除模块 docstring 中的 Apache 2.0 LICENSE 文本。"""
    if what != "module" or not lines:
        return
    # 检测首行是否为 Copyright
    if lines[0].strip().startswith("Copyright"):
        # 从后往前找 LICENSE 结束行（"limitations under the License."）
        for i in range(len(lines) - 1, -1, -1):
            if "limitations under the License." in lines[i]:
                del lines[: i + 1]
                break


def setup(app):
    app.connect("autodoc-process-docstring", _strip_license)
