"""The map's tiles: scored hexes as one static PMTiles archive.

CS-207. A build step rather than a server, because the alternative is a tile
server to run, monitor and pay for in order to hand out bytes that never change
between runs.
"""

from pipeline.tiles.build import (
    LAYER_NAME,
    ScoredHex,
    TileBuild,
    build_archive,
)

__all__ = ["LAYER_NAME", "ScoredHex", "TileBuild", "build_archive"]
