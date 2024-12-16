from asyncio.proactor_events import _ProactorBasePipeTransport
from datetime import datetime
from functools import wraps
from aiohttp import ClientSession

from pytile.api import async_login
from pytile.errors import TileError
from pytile.tile import Tile

import logging

# Code copied from
# https://pythonalgos.com/runtimeerror-event-loop-is-closed-asyncio-fix
"""fix yelling at me error"""


def silence_event_loop_closed(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except RuntimeError as e:
            if str(e) != 'Event loop is closed':
                raise
    return wrapper


_ProactorBasePipeTransport.__del__ = silence_event_loop_closed(_ProactorBasePipeTransport.__del__)
"""fix yelling at me error end"""


class TileConnector:
    def __init__(self, tile_conf: dict) -> None:
        self.user: str = tile_conf["username"]
        self.password: str = tile_conf["password"]
        self.include: set[str] = set(tile_conf["include"])
        self.exclude: set[str] = set(tile_conf["exclude"])
        self.warn_if_older_days = int(tile_conf["warn_if_older_days"])
        self.tiles: list[Tile] = list()
        self.last_update: dict[str, datetime] = dict()

    def __get_name(self, tile: Tile) -> str:
        return f"'{tile.name}' ({tile.uuid})"

    async def refresh(self) -> None:
        async with ClientSession() as session:
            try:
                api = await async_login(self.user, self.password, session)
                for tile in self.tiles:
                    tile._async_request = api._async_request
                    await tile.async_update()
            except TileError as err:
                logging.error(err)

    def __is_included(self, tile: Tile) -> bool:
        if self.include and not tile.name in self.include and not tile.uuid in self.include:
            return False
        if self.exclude and (tile.name in self.exclude or tile.uuid in self.exclude):
            return False
        return True

    async def discover(self) -> None:
        async with ClientSession() as session:
            try:
                api = await async_login(self.user, self.password, session)

                tiles = await api.async_get_tiles()

                for tile in tiles.values():
                    name = self.__get_name(tile)
                    if self.__is_included(tile):
                        logging.info(f"Tracking tile {name}.")
                        self.tiles.append(tile)
                    else:
                        logging.debug(f"Not tracking tile {name}.")
            except TileError as err:
                logging.error(err)

    def get_records(self, measurement_name: str) -> list:
        records = []
        for tile in self.tiles:
            if not tile.latitude or not tile.longitude or not tile.last_timestamp:
                logging.warning(f"Tile {self.__get_name(tile)} missing location or time.")
                continue
            # Remove the millisecond precision, given that the measures aren't precise anyway
            time = tile.last_timestamp.replace(microsecond=0)

            if tile.uuid not in self.last_update:
                self.last_update[tile.uuid] = time
                days_diff = (datetime.now()-time).days
                if days_diff >= self.warn_if_older_days:
                    logging.warning(f"Tile {tile.name}, {tile.uuid} was last updated {days_diff} day(s) ago.")
            else:
                if self.last_update[tile.uuid] == time:
                    continue # no need to re-import the same record if no changes
                self.last_update[tile.uuid] = time

            records.append(
                {
                    "measurement": measurement_name,
                    "tags": {
                        "uuid": tile.uuid,
                        "name": tile.name,
                    },
                    "fields": {
                        "latitude": tile.latitude,
                        "longitude": tile.longitude,
                    },
                    "time": time,
                }
            )
        return records
