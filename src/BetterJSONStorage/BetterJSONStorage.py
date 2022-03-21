import _thread as Thread
from pathlib import Path
from typing import Literal, Mapping, Optional, Set

from blosc2 import compress, decompress
from orjson import dumps, loads

class BetterJSONStorage:
    """
    A class that represents a storage interface for reading and writing to a file.


    Attributes
    ----------
    `path: str`
        Path to file, if it does not exist it will be created only if the the 'r+' access mode is set.

    `access_mode: str, optional`
        Options are `'r'` for readonly (default), or `'r+'` for writing and reading.

    `kwargs:`
        These attributes will be passed on to `orjson.dumps`

    Methods
    -------
    `read() -> Mapping:`
        Returns the data from memory.

    `write(data: Mapping) -> None:`
        Writes data to file if acces mode is set to `r+`.

    `load() -> None:`
        loads the data from disk. This happens on object creation.
        Can be used when you suspect the data in memory and on disk are not in sync anymore.

    Raises
    ------
    `FileNotFoundError` when the file doesn't exist and `r+` is not set

    Notes
    ----
    If the directory specified in `path` does not exist it will only be created if access_mode is set to `'r+'`.
    """

    __slots__ = (
        "_hash",
        "_access_mode",
        "_path",
        "_data",
        "_kwargs",
        "_changed",
        "_running",
        "_shutdown_lock",
        "_handle"
    )

    _paths: Set[int] = set()

    def __init__(
        self, path: Path = Path(), access_mode: Literal["r", "r+"] = "r", **kwargs
    ):
        # flags
        self._shutdown_lock = Thread.allocate_lock()
        self._running = True
        self._changed = False

        # checks
        self._hash = hash(path)

        if not access_mode in {"r", "r+"}:
            self.close()
            raise AttributeError(f'access_mode is not one of ("r", "r+"), :{access_mode}')

        if not isinstance(path, Path):
            self.close()
            raise TypeError("path is not an instance of pathlib.Path")

        if not path.exists():
            if access_mode == "r":
                self.close()
                raise FileNotFoundError(
                    f"""File can't be found, use access_mode='r+' if you wan to create it.
                        Path: <{path.absolute()}>,
                        """
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = path.open('wb+')
        if not path.is_file():
            self.close()
            raise FileNotFoundError(
                f"""path does not lead to a file: <{path.absolute()}>."""
            )
        else:
            self._handle = path.open('wb')

        self._access_mode = access_mode
        self._path = path

        # rest
        self._kwargs = kwargs
        self._data: Optional[Mapping]

        # finishing init
        self.load()
        Thread.start_new_thread(self.__file_writer, ())

    def __new__(class_, path, *args, **kwargs):
        h = hash(path)
        if h in class_._paths:
            raise AttributeError(
                f'A BetterJSONStorage object already exists with path < "{path}" >'
            )
        class_._paths.add(h)
        instance = object.__new__(class_)
        return instance

    def __repr__(self):
        return (
            f"""BetterJSONStorage(path={self._path}, Paths={self.__class__._paths})"""
        )

    def read(self):
        return self._data

    def __file_writer(self):
        self._shutdown_lock.acquire()
        while self._running:

            if self._changed:
                self._changed = False
                self._handle.write(compress(dumps(self._data)))

        self._shutdown_lock.release()

    def write(self, data: Mapping):
        if not self._access_mode == "r+":
            raise PermissionError("Storage is openend as read only")
        self._data = data
        self._changed = True

    def load(self) -> None:
        if len(db_bytes := self._path.read_bytes()):

            self._data = loads(decompress(db_bytes))
        else:
            self._data = None

    def close(self):
        while self._changed:
            ...
        self._running = False
        self._shutdown_lock.acquire()
        self._handle.flush()
        self._handle.close()
        self.__class__._paths.discard(self._hash)
