#!/usr/bin/env python3
"""Setup script for Galaxy Workflow Checker (gwc)."""

from setuptools import setup, find_packages

setup(
    name="galaxy-workflow-checker",
    version="2.0.0",
    description="Check whether Galaxy workflow tools are installed in a Galaxy instance",
    author="Your Name",
    author_email="your.email@example.com",
    packages=find_packages(),
    package_data={
        "gwc": ["config.yaml"],
    },
    install_requires=[
        "PyYAML>=6.0",
        "bioblend>=1.0.0",
        "requests>=2.25.0",
        "tabulate>=0.8.0"
    ],
    entry_points={
        "console_scripts": [
            "gwc=gwc.main:main",
            "galaxy-check=gwc.main:main",
        ],
    },
    python_requires=">=3.7",
)
