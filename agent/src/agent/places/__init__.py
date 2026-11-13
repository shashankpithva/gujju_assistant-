"""Gujarat's districts, talukas, villages and towns: the list the survey checks each place against.

survey/flow.py writes a village, taluka or district in the sheet only if it's in this list and the
person has said yes to it being read back. Where the list comes from: data/README.md.
"""

from __future__ import annotations

import logging
import os

from agent.places.gazetteer import Gazetteer, Match, Place, gujarat

__all__ = ["Gazetteer", "Match", "Place", "gujarat", "load_places"]

logger = logging.getLogger("agent.places")


def load_places() -> Gazetteer | None:
    """The list to check places against, or None with PLACE_CHECK=off, or if it can't be loaded:
    places are then read back as heard, and still go in the sheet only after a yes."""
    if os.getenv("PLACE_CHECK", "on").strip().lower() == "off":
        logger.info("PLACE_CHECK=off: places are read back as heard, not checked against the list")
        return None
    try:
        return gujarat()
    except Exception:
        logger.exception("the list of Gujarat's places couldn't be loaded: places won't be checked")
        return None
