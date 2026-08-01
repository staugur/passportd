# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import sys
import tempfile
from pallets_sphinx_themes import get_version, ProjectLink

sys.path.insert(0, os.path.abspath("../"))

# autodoc 需要导入项目模块，但模块导入时会触发数据库连接。
# 在此设置环境变量使用临时 SQLite 数据库，确保文档构建不依赖实际数据库。
if "PASSPORT_DB_URI" not in os.environ:
    _tmp_db = os.path.join(tempfile.gettempdir(), "passportd_docs.db")
    os.environ["PASSPORT_DB_URI"] = f"sqlite:///{_tmp_db}"

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
