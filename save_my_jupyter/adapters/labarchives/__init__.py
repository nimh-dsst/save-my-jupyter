"""LabArchives delivery adapter (target DELIVER). The metadata-page renderer is
pure and tested here; the labapi client glue is isolated in `delivery.py` and is
gate-unverifiable (it needs a real LabArchives account)."""

from __future__ import annotations
