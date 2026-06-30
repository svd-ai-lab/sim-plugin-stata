"""Stata driver plugin for sim-cli.

Distributed as an out-of-tree plugin; discovered by sim-cli via the
``sim.drivers`` entry-point group. Bundled skill files (under ``_skills/``)
are exposed via the ``sim.skills`` entry-point group.

Stata is driven through its batch CLI (one-shot ``.do`` files) and the
official ``pystata`` Python API (persistent sessions) — no GUI automation.
"""
from importlib.resources import files

from .driver import StataDriver

skills_dir = files(__name__) / "_skills"


plugin_info = {
    "name": "stata",
    "summary": "Stata statistics/econometrics driver plugin for sim-cli.",
    "homepage": "https://github.com/svd-ai-lab/sim-plugin-stata",
    "license_class": "commercial",
    "solver_name": "stata",
}

__all__ = ["StataDriver", "skills_dir", "plugin_info"]
