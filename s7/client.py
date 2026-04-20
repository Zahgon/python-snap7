"""Unified S7 client with protocol auto-discovery.

Provides a single client that automatically selects the best protocol
(S7CommPlus or legacy S7) for communicating with Siemens S7 PLCs.

Usage::

    from s7 import Client

    client = Client()
    client.connect("192.168.1.10", 0, 1)
    data = client.db_read(1, 0, 4)
"""

import logging
from typing import Any, Optional

from snap7.client import Client as LegacyClient

from ._protocol import Protocol
from ._s7commplus_client import S7CommPlusClient

logger = logging.getLogger(__name__)


class Client:
    """Unified S7 client with protocol auto-discovery.

    Automatically selects the best protocol for the target PLC:
    - S7CommPlus for S7-1200/1500 PLCs with full data operations
    - Legacy S7 for S7-300/400 or when S7CommPlus is unavailable

    Methods not explicitly defined are delegated to the underlying
    legacy client via ``__getattr__``.

    Example::

        from s7 import Client

        client = Client()
        client.connect("192.168.1.10", 0, 1)
        data = client.db_read(1, 0, 4)
        print(client.protocol)
    """

    def __init__(self) -> None:
        self._legacy: Optional[LegacyClient] = None
        self._plus: Optional[S7CommPlusClient] = None
        self._protocol: Protocol = Protocol.AUTO
        self._host: str = ""
        self._port: int = 102
        self._rack: int = 0
        self._slot: int = 1

    @property
    def protocol(self) -> Protocol:
        """The protocol currently in use for DB operations."""
        pass

    @property
    def connected(self) -> bool:
        """Whether the client is connected to a PLC."""
        pass

    def connect(
        self,
        address: str,
        rack: int = 0,
        slot: int = 1,
        tcp_port: int = 102,
        *,
        protocol: Protocol = Protocol.AUTO,
        use_tls: bool = False,
        tls_cert: Optional[str] = None,
        tls_key: Optional[str] = None,
        tls_ca: Optional[str] = None,
        password: Optional[str] = None,
    ) -> "Client":
        """Connect to an S7 PLC.

        Args:
            address: PLC IP address or hostname.
            rack: PLC rack number.
            slot: PLC slot number.
            tcp_port: TCP port (default 102).
            protocol: Protocol selection. AUTO tries S7CommPlus first,
                then falls back to legacy S7.
            use_tls: Whether to activate TLS (required for V2+).
            tls_cert: Path to client TLS certificate (PEM).
            tls_key: Path to client private key (PEM).
            tls_ca: Path to CA certificate for PLC verification (PEM).
            password: PLC password for legitimation (V2+ with TLS).

        Returns:
            self, for method chaining.
        """
        pass

    def _try_s7commplus(
        self,
        address: str,
        tcp_port: int,
        rack: int,
        slot: int,
        *,
        use_tls: bool = False,
        tls_cert: Optional[str] = None,
        tls_key: Optional[str] = None,
        tls_ca: Optional[str] = None,
        password: Optional[str] = None,
    ) -> bool:
        """Try to establish an S7CommPlus connection.

        Returns True if S7CommPlus data operations are available.
        """
        pass

    def disconnect(self) -> int:
        """Disconnect from PLC.

        Returns:
            0 on success (matches snap7.Client).
        """
        pass

    def db_read(self, db_number: int, start: int, size: int) -> bytearray:
        """Read raw bytes from a data block.

        Uses S7CommPlus when available, otherwise legacy S7.
        """
        pass

    def db_write(self, db_number: int, start: int, data: bytearray) -> int:
        """Write raw bytes to a data block.

        Uses S7CommPlus when available, otherwise legacy S7.

        Returns:
            0 on success (matches snap7.Client).
        """
        pass

    def db_read_multi(self, items: list[tuple[int, int, int]]) -> list[bytearray]:
        """Read multiple data block regions in a single request.

        Uses S7CommPlus native multi-read when available.
        """
        pass

    def explore(self, explore_id: int = 0) -> bytes:
        """Browse the PLC object tree (S7CommPlus only).

        Args:
            explore_id: Object to explore (0 = root).

        Raises:
            RuntimeError: If not connected via S7CommPlus.
        """
        pass

    def list_datablocks(self) -> list[dict[str, Any]]:
        """List all datablocks on the PLC.

        .. warning:: This method is **experimental** and may change.

        Uses S7CommPlus EXPLORE when available, otherwise falls back to
        legacy ``list_blocks_of_type``.

        Returns:
            List of dicts with keys ``name``, ``number``, ``rid``.
        """
        pass

    def browse(self) -> list[dict[str, Any]]:
        """Browse the PLC symbol table.

        .. warning:: This method is **experimental** and may change.

        Returns a flat list of variable info dicts. Can be used to create
        a :class:`~snap7.util.symbols.SymbolTable`::

            symbols = SymbolTable.from_browse(client.browse())

        Requires S7CommPlus connection.
        """
        pass

    def read_diagnostic_buffer(self) -> list[dict[str, Any]]:
        """Read the PLC diagnostic buffer.

        .. warning:: This method is **experimental** and may change.

        Uses the legacy S7 protocol (SZL read).
        """
        pass

    def create_subscription(self, items: list[tuple[int, int, int]], cycle_ms: int = 0) -> int:
        """Create a data change subscription (S7CommPlus only).

        .. warning:: This method is **experimental** and may change.

        Args:
            items: List of (db_number, start_offset, size) tuples.
            cycle_ms: Cycle time in milliseconds (0 = on change).

        Returns:
            Subscription ID.
        """
        pass

    def delete_subscription(self, subscription_id: int) -> None:
        """Delete a data change subscription (S7CommPlus only).

        .. warning:: This method is **experimental** and may change.
        """
        pass

    def upload_block(self, block_type: int, block_number: int) -> bytes:
        """Upload (read) a program block from the PLC.

        .. warning:: This method is **experimental** and may change.

        Uses S7CommPlus when available, otherwise falls back to legacy
        ``full_upload``.
        """
        pass

    def download_block(self, block_type: int, block_number: int, data: bytes) -> None:
        """Download (write) a program block to the PLC.

        .. warning:: This method is **experimental** and may change.

        Uses S7CommPlus when available, otherwise falls back to legacy
        ``download``.
        """
        pass

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown methods to the legacy client."""
        if name.startswith("_"):
            raise AttributeError(name)
        if self._legacy is not None:
            return getattr(self._legacy, name)
        raise AttributeError(f"'Client' object has no attribute {name!r} (not connected)")

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *args: Any) -> None:
        self.disconnect()

    def __repr__(self) -> str:
        if self.connected:
            return f"<s7.Client {self._host}:{self._port} protocol={self._protocol.value}>"
        return "<s7.Client disconnected>"
