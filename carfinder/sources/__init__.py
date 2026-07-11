"""Source registry."""

from __future__ import annotations

from .base import Source
from .carsales import Carsales
from .autotrader import Autotrader
from .carsguide import CarsGuide
from .gumtree import Gumtree
from .drive import Drive
from .demo import Demo

# Order controls scrape + report order. "demo" is opt-in only.
ALL_SOURCES: dict[str, type[Source]] = {
    "carsales": Carsales,
    "autotrader": Autotrader,
    "carsguide": CarsGuide,
    "gumtree": Gumtree,
    "drive": Drive,
    "demo": Demo,
}

DEFAULT_SOURCES = [name for name in ALL_SOURCES if name != "demo"]
