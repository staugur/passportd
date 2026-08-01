# -*- coding: utf-8 -*-

import os

from setuptools import setup, find_namespace_packages
from passportd.version import __version__


def get_requires(env: str) -> list:
    """Parse requirements file and resolve ``-r`` references."""
    here = os.path.abspath(os.path.dirname(__file__))
    reqs = []

    def _parse(filepath):
        with open(filepath, "r") as fp:
            for line in fp:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("-r "):
                    ref = line[3:].strip()
                    _parse(os.path.join(os.path.dirname(filepath), ref))
                else:
                    reqs.append(line)

    _parse(os.path.join(here, "requirements", f"{env}.txt"))
    return reqs


def get_readme() -> str:
    here = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(here, "README.md"), encoding="utf-8") as f:
        return f.read()


gh = "https://github.com/staugur/passportd"
setup(
    name="passportd",
    version=__version__,
    author="Hiroshi.tao",
    author_email="me@tcw.im",
    license="Apache-2.0",
    url=gh,
    project_urls={
        "Code": gh,
        "Issue tracker": "{gh}/issues".format(gh=gh),
        "Documentation": "https://passportd.readthedocs.io/",
        "Releases": "{gh}/releases".format(gh=gh),
    },
    keywords="sso,auth,signup,signin",
    description="Unified login module for my personal application",
    long_description=get_readme(),
    long_description_content_type="text/markdown",
    packages=find_namespace_packages(include=["passportd", "passportd.*"]),
    include_package_data=True,
    zip_safe=False,
    platforms=["any"],
    python_requires=">=3.10",
    install_requires=get_requires("prod"),
    entry_points={"console_scripts": ["passportd = passportd.cli:cli"]},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Framework :: Flask",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Internet :: WWW/HTTP :: Dynamic Content",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)
