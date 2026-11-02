# -*- coding: utf-8 -*-
"""가짜 pystata.config(테스트 전용)."""
import os
import sys

STATE = {"initialized": False, "edition": None, "graph_show": True}


def init(edition, splash=True):
    if os.environ.get("FAKE_PYSTATA_FAIL"):
        raise RuntimeError("fake license failure")
    if edition not in ("mp", "se", "be"):
        raise ValueError("edition must be mp, se, or be")
    if splash:
        sys.stdout.write("  ___  ____  ____  ____  ____ (fake splash)\n")
    STATE["initialized"] = True
    STATE["edition"] = edition


def is_stata_initialized():
    return STATE["initialized"]


def set_graph_show(show, perm=False):
    STATE["graph_show"] = bool(show)
