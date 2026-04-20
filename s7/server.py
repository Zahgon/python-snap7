"""Unified S7 server supporting both legacy S7 and S7CommPlus clients.

Wraps both a legacy :class:`snap7.server.Server` and an
:class:`S7CommPlusServer` so that test environments can serve both
protocol stacks simultaneously.

Usage::

    from s7 import Server

    server = Server()
    server.start(tcp_port=102, s7commplus_port=11020)
"""

import logging
from typing import Any, Optional

from snap7.server import Server as LegacyServer

from ._s7commplus_server import S7CommPlusServer, DataBlock

logger = logging.getLogger(__name__)


class Server:
    """Unified S7 server for testing.

    Runs a legacy S7 server and optionally an S7CommPlus server
    side by side.
    """

    def __init__(self) -> None:
        self._legacy = LegacyServer()
        self._plus = S7CommPlusServer()

    @property
    def legacy_server(self) -> LegacyServer:
        """Direct access to the legacy S7 server."""
        pass

    @property
    def s7commplus_server(self) -> S7CommPlusServer:
        """Direct access to the S7CommPlus server."""
        pass

    def register_db(
        self,
        db_number: int,
        variables: dict[str, tuple[str, int]],
        size: int = 0,
    ) -> DataBlock:
        """Register a data block on the S7CommPlus server.

        Args:
            db_number: Data block number
            variables: Dict of {name: (type_name, offset)}
            size: Total DB size in bytes (auto-calculated if 0)

        Returns:
            The created DataBlock
        """
        pass

    def register_raw_db(self, db_number: int, data: bytearray) -> DataBlock:
        """Register a raw data block on the S7CommPlus server.

        Args:
            db_number: Data block number
            data: Raw bytearray backing the data block

        Returns:
            The created DataBlock
        """
        pass

    def get_db(self, db_number: int) -> Optional[DataBlock]:
        """Get a registered data block."""
        pass

    def start(
        self,
        tcp_port: int = 102,
        s7commplus_port: Optional[int] = None,
        *,
        use_tls: bool = False,
        tls_cert: Optional[str] = None,
        tls_key: Optional[str] = None,
    ) -> None:
        """Start the server(s).

        Args:
            tcp_port: Port for the legacy S7 server.
            s7commplus_port: Port for the S7CommPlus server. If None,
                only the legacy server is started.
            use_tls: Whether to enable TLS on the S7CommPlus server.
            tls_cert: Path to TLS certificate (PEM).
            tls_key: Path to TLS private key (PEM).
        """
        pass

    def stop(self) -> None:
        """Stop all servers."""
        pass

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown methods to the legacy server."""
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._legacy, name)

    def __enter__(self) -> "Server":
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()
