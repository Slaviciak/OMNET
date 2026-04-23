#!/usr/bin/env python3
"""
Backward-compatible wrapper for exporting only the logistic runtime artifact.

This keeps the older workflow entrypoint available while the newer
multi-candidate runtime export path lives in analysis/export_runtime_models.py.
"""

from __future__ import annotations

from export_runtime_models import main


if __name__ == "__main__":
    main(
        default_model_families=["logistic_regression"],
        default_manifest_output=None,
    )
