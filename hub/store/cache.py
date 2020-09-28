import os
import zarr
import json


class CacheStore(zarr.LMDBStore):
    def __init__(self, path, buffers=True, cache_reset=True, **kwargs):
        """
        Extends zarr.LMDB store to support Ordered Dictionary map

        Parameters
        ----------
        path : string
            Location of database file.
        buffers : bool, optional
            If True (default) use support for buffers, which should increase performance by
            reducing memory copies.
        cache_reset: bool, optional
            cleans up the cach
        **kwargs
            Keyword arguments passed through to the `lmdb.open` function.

        """
        super(CacheStore, self).__init__(path, buffers=True, **kwargs)
        if cache_reset:
            for k, v in self.items():
                del self[k]
            self._order = ["_order"]

    @property
    def _order(self):
        try:
            order = json.loads(super().__getitem__("_order").tobytes())
            return order
        except KeyError:
            self._order = ["_order"]
        return []

    @_order.setter
    def _order(self, x):
        super().__setitem__("_order", json.dumps(x).encode())

    def _key_format(self, key):
        """ Zarr sometimes inserts tuple, but lmbd can't have tuple key (".zgroup", "z.group") """
        if isinstance(key, tuple):
            key = key[0]
        return key

    def move_to_end(self, key):
        """Move key to the end"""
        key = self._key_format(key)
        order = self._order
        ind = order.index(key)
        el = order.pop(ind)
        order.append(el)
        self._order = order

    def popitem(self, last=False):
        """Remove the first value from the cache, as this will be the least recently"""
        order = self._order
        key = order.pop(0)
        self._ordere = order
        return key, self.pop(key, key_removed=True)

    def pop(self, key, key_removed=False):
        """Remove an element from the cache"""
        key = self._key_format(key)

        if not key_removed:
            order = self._order
            if key in order:
                order.remove(key)
                self._order = order

        el = self[key]
        del self[key]
        return el

    def __setitem__(self, key, value):
        """On each new add, remember the order"""
        order = self._order
        if key in order:
            order.remove(key)
        order.append(key)
        self._order = order
        key = self._key_format(key)
        super().__setitem__(key, value)

    def __getitem__(self, key):
        """On each new add, remember the order"""
        key = self._key_format(key)
        el = super().__getitem__(key)
        return el

    def __delitem__(self, key):
        """ Delete item """
        key = self._key_format(key)
        order = self._order
        if key in order:
            order.remove(key)
        self._order = order
        super().__delitem__(key)

    def clear(self):
        """ Clean up the cache """
        for k, v in self.items():
            if k != "_order" and k != "_values_cache":
                del self[k]


class Cache(zarr.LRUStoreCache):
    def __init__(self, store, max_size, path="~/.activeloop/cache"):
        """
        Extends zarr.LRUStoreCache with LMBD Cache that could be shared across

        Storage class that implements a least-recently-used (LRU) cache layer over
        some other store. Intended primarily for use with stores that can be slow to
        access, e.g., remote stores that require network communication to store and
        retrieve data.

        Parameters
        ----------
        store : MutableMapping
            The store containing the actual data to be cached.
        max_size : int
            The maximum size that the cache may grow to, in number of bytes. Provide `None`
            if you would like the cache to have unlimited size.
        """
        super(Cache, self).__init__(store, max_size)
        self.path = os.path.expanduser(path)
        os.makedirs(self.path, exist_ok=True)
        self._values_cache = CacheStore(self.path, buffers=True)
        self.cache_key = "_current_size"

    @property
    def _current_size(self):
        """ get size counter from the cache """
        if "_values_cache" not in dir(self) or self.cache_key not in self._values_cache:
            return 0
        return int.from_bytes(
            self._values_cache[self.cache_key], byteorder="big", signed=True
        )

    @_current_size.setter
    def _current_size(self, x):
        """ set size counter to the cache """
        if "_values_cache" not in dir(self):
            return
        self._values_cache[self.cache_key] = int.to_bytes(
            x, length=32, byteorder="big", signed=True
        )

    def commit(self):
        """ closes the cache db """
        self._values_cache.close()