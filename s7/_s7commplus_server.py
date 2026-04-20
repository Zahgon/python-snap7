"""
S7CommPlus server emulator for testing.

Emulates an S7-1200/1500 PLC for integration testing without real hardware.
Handles the S7CommPlus protocol including:
- COTP connection setup (reuses ISOTCPConnection transport)
- CreateObject session handshake
- Explore (browse registered data blocks and variables)
- GetMultiVariables / SetMultiVariables (read/write by address)
- Internal PLC memory model with thread-safe access
- V2 protocol emulation with TLS and IntegrityId tracking

Supports both V1 (no TLS) and V2 (TLS + IntegrityId) emulation.

Usage::

    server = S7CommPlusServer()
    server.register_db(1, {"temperature": ("Real", 0), "pressure": ("Real", 4)})
    server.start(port=11020)

    # V2 server with TLS:
    server = S7CommPlusServer(protocol_version=ProtocolVersion.V2)
    server.start(port=11020, use_tls=True, tls_cert="cert.pem", tls_key="key.pem")
"""

import logging
import socket
import ssl
import struct
import threading
from enum import IntEnum
from typing import Any, Callable, Optional

from .protocol import (
    DataType,
    ElementID,
    FunctionCode,
    Ids,
    Opcode,
    ProtocolVersion,
    READ_FUNCTION_CODES,
    SoftDataType,
)
from .vlq import encode_uint32_vlq, decode_uint32_vlq, encode_uint64_vlq
from .codec import (
    encode_header,
    decode_header,
    encode_typed_value,
    encode_pvalue_blob,
    decode_pvalue_to_bytes,
)

logger = logging.getLogger(__name__)


class CPUState(IntEnum):
    """Emulated CPU operational state."""

    UNKNOWN = 0
    STOP = 1
    RUN = 2


# Mapping from SoftDataType to wire DataType and byte size
_SOFT_TO_WIRE: dict[int, tuple[int, int]] = {
    SoftDataType.BOOL: (DataType.BOOL, 1),
    SoftDataType.BYTE: (DataType.BYTE, 1),
    SoftDataType.CHAR: (DataType.BYTE, 1),
    SoftDataType.WORD: (DataType.WORD, 2),
    SoftDataType.INT: (DataType.INT, 2),
    SoftDataType.DWORD: (DataType.DWORD, 4),
    SoftDataType.DINT: (DataType.DINT, 4),
    SoftDataType.REAL: (DataType.REAL, 4),
    SoftDataType.LREAL: (DataType.LREAL, 8),
    SoftDataType.USINT: (DataType.USINT, 1),
    SoftDataType.UINT: (DataType.UINT, 2),
    SoftDataType.UDINT: (DataType.UDINT, 4),
    SoftDataType.SINT: (DataType.SINT, 1),
    SoftDataType.ULINT: (DataType.ULINT, 8),
    SoftDataType.LINT: (DataType.LINT, 8),
    SoftDataType.LWORD: (DataType.LWORD, 8),
    SoftDataType.STRING: (DataType.S7STRING, 256),
    SoftDataType.WSTRING: (DataType.WSTRING, 512),
}

# Map string type names to SoftDataType values
_TYPE_NAME_MAP: dict[str, int] = {
    "Bool": SoftDataType.BOOL,
    "Byte": SoftDataType.BYTE,
    "Char": SoftDataType.CHAR,
    "Word": SoftDataType.WORD,
    "Int": SoftDataType.INT,
    "DWord": SoftDataType.DWORD,
    "DInt": SoftDataType.DINT,
    "Real": SoftDataType.REAL,
    "LReal": SoftDataType.LREAL,
    "USInt": SoftDataType.USINT,
    "UInt": SoftDataType.UINT,
    "UDInt": SoftDataType.UDINT,
    "SInt": SoftDataType.SINT,
    "ULInt": SoftDataType.ULINT,
    "LInt": SoftDataType.LINT,
    "LWord": SoftDataType.LWORD,
    "String": SoftDataType.STRING,
    "WString": SoftDataType.WSTRING,
}


class DBVariable:
    """A variable in a data block."""

    def __init__(self, name: str, soft_datatype: int, byte_offset: int):
        self.name = name
        self.soft_datatype = soft_datatype
        self.byte_offset = byte_offset

        wire_info = _SOFT_TO_WIRE.get(soft_datatype, (DataType.BYTE, 1))
        self.wire_datatype = wire_info[0]
        self.byte_size = wire_info[1]

    def __repr__(self) -> str:
        return f"DBVariable({self.name!r}, type={self.soft_datatype}, offset={self.byte_offset})"


class DataBlock:
    """An emulated PLC data block with named variables."""

    def __init__(self, number: int, size: int = 1024):
        self.number = number
        self.data = bytearray(size)
        self.variables: dict[str, DBVariable] = {}
        self.lock = threading.Lock()
        # Assign a unique object ID for the S7CommPlus object tree
        self.object_id = 0x00010000 | (number & 0xFFFF)

    def add_variable(self, name: str, type_name: str, byte_offset: int) -> None:
        """Register a named variable in this data block.

        Args:
            name: Variable name (e.g. "temperature")
            type_name: PLC type name (e.g. "Real", "Int", "Bool")
            byte_offset: Byte offset within the data block
        """
        pass

    def read(self, offset: int, size: int) -> bytes:
        """Read bytes from the data block."""
        pass

    def write(self, offset: int, data: bytes) -> None:
        """Write bytes to the data block."""
        pass

    def read_variable(self, name: str) -> tuple[int, bytes]:
        """Read a named variable.

        Returns:
            Tuple of (wire_datatype, raw_bytes)
        """
        pass

    def write_variable(self, name: str, data: bytes) -> None:
        """Write a named variable."""
        pass


class S7CommPlusServer:
    """S7CommPlus PLC emulator for testing.

    Emulates an S7-1200/1500 PLC with:
    - Internal data block storage with named variables
    - S7CommPlus protocol handling (V1 and V2)
    - V2 TLS support with IntegrityId tracking
    - Multi-client support (threaded)
    - CPU state management
    """

    def __init__(self, protocol_version: int = ProtocolVersion.V1) -> None:
        self._data_blocks: dict[int, DataBlock] = {}
        self._cpu_state = CPUState.RUN
        self._protocol_version = protocol_version
        self._next_session_id = 1

        self._server_socket: Optional[socket.socket] = None
        self._server_thread: Optional[threading.Thread] = None
        self._client_threads: list[threading.Thread] = []
        self._running = False
        self._lock = threading.Lock()
        self._event_callback: Optional[Callable[..., None]] = None

        # TLS configuration (V2)
        self._ssl_context: Optional[ssl.SSLContext] = None
        self._use_tls: bool = False

    @property
    def cpu_state(self) -> CPUState:
        pass

    @cpu_state.setter
    def cpu_state(self, state: CPUState) -> None:
        pass

    def register_db(self, db_number: int, variables: dict[str, tuple[str, int]], size: int = 1024) -> DataBlock:
        """Register a data block with named variables.

        Args:
            db_number: Data block number (e.g. 1 for DB1)
            variables: Dict mapping variable name to (type_name, byte_offset)
                       e.g. {"temperature": ("Real", 0), "count": ("Int", 4)}
            size: Data block size in bytes

        Returns:
            The created DataBlock

        Example::

            server.register_db(1, {
                "temperature": ("Real", 0),
                "pressure": ("Real", 4),
                "running": ("Bool", 8),
                "count": ("DInt", 10),
            })
        """
        pass

    def register_raw_db(self, db_number: int, data: bytearray) -> DataBlock:
        """Register a data block with raw data (no named variables).

        Args:
            db_number: Data block number
            data: Initial data block content

        Returns:
            The created DataBlock
        """
        pass

    def get_db(self, db_number: int) -> Optional[DataBlock]:
        """Get a registered data block."""
        pass

    def start(
        self,
        host: str = "0.0.0.0",
        port: int = 11020,
        use_tls: bool = False,
        tls_cert: Optional[str] = None,
        tls_key: Optional[str] = None,
        tls_ca: Optional[str] = None,
    ) -> None:
        """Start the server.

        Args:
            host: Bind address
            port: TCP port to listen on
            use_tls: Whether to wrap client sockets with TLS after InitSSL
            tls_cert: Path to server TLS certificate (PEM)
            tls_key: Path to server private key (PEM)
            tls_ca: Path to CA certificate for client verification (PEM)
        """
        pass

    def stop(self) -> None:
        """Stop the server."""
        pass

    def _server_loop(self) -> None:
        """Main server accept loop."""
        pass

    def _handle_client(self, client_sock: socket.socket, address: tuple[str, int]) -> None:
        """Handle a single client connection."""
        pass

    def _handle_cotp_connect(self, sock: socket.socket) -> bool:
        """Handle COTP Connection Request / Confirm."""
        pass

    def _recv_s7commplus_frame(self, sock: socket.socket) -> Optional[bytes]:
        """Receive a TPKT/COTP/S7CommPlus frame, return the S7CommPlus payload."""
        pass

    def _send_s7commplus_frame(self, sock: socket.socket, data: bytes) -> None:
        """Send an S7CommPlus frame wrapped in TPKT/COTP."""
        pass

    def _process_request(
        self,
        data: bytes,
        session_id: int,
        integrity_id_read: int = 0,
        integrity_id_write: int = 0,
    ) -> Optional[bytes]:
        """Process an S7CommPlus request and return a response."""
        pass

    def _build_response_header(
        self,
        function_code: int,
        seq_num: int,
        session_id: int,
        include_integrity_id: bool = False,
        integrity_id: int = 0,
    ) -> bytes:
        """Build a 14-byte response header, optionally with IntegrityId (V2+).

        Args:
            function_code: Response function code
            seq_num: Sequence number echoed from request
            session_id: Session ID
            include_integrity_id: If True, append VLQ IntegrityId after header
            integrity_id: IntegrityId value to include

        Returns:
            Response header bytes (14 bytes, or 14+VLQ for V2+)
        """
        pass

    def _handle_init_ssl(self, seq_num: int) -> bytes:
        """Handle InitSSL -- respond to SSL initialization (V1 emulation, no real TLS)."""
        pass

    def _handle_create_object(self, seq_num: int, request_data: bytes) -> bytes:
        """Handle CreateObject -- establish a session."""
        pass

    def _handle_delete_object(self, seq_num: int, session_id: int) -> bytes:
        """Handle DeleteObject -- close a session."""
        pass

    def _handle_explore(self, seq_num: int, session_id: int, request_data: bytes) -> bytes:
        """Handle Explore -- return the object tree (registered data blocks)."""
        pass

    def _handle_get_multi_variables(self, seq_num: int, session_id: int, request_data: bytes) -> bytes:
        """Handle GetMultiVariables -- read variables from data blocks.

        Parses the S7CommPlus request format with ItemAddress structures.
        The server extracts db_number from AccessArea and byte offset/size
        from the LID values.

        Reference: thomas-v2/S7CommPlusDriver/Core/GetMultiVariablesRequest.cs
        """
        pass

    def _handle_set_multi_variables(self, seq_num: int, session_id: int, request_data: bytes) -> bytes:
        """Handle SetMultiVariables -- write variables to data blocks.

        Reference: thomas-v2/S7CommPlusDriver/Core/SetMultiVariablesRequest.cs
        """
        pass

    def _build_error_response(self, seq_num: int, session_id: int, function_code: int) -> bytes:
        """Build a generic error response for unsupported function codes."""
        pass

    @staticmethod
    def _recv_exact(sock: socket.socket, size: int) -> bytes:
        """Receive exactly the specified number of bytes."""
        pass

    def __enter__(self) -> "S7CommPlusServer":
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()


# -- Server-side request parsers --


def _server_parse_read_request(request_data: bytes) -> list[tuple[int, int, int]]:
    """Parse a GetMultiVariables request payload on the server side.

    Extracts (db_number, byte_offset, byte_size) for each item from the
    S7CommPlus ItemAddress format.

    Returns:
        List of (db_number, byte_offset, byte_size) tuples
    """
    pass


def _server_parse_write_request(request_data: bytes) -> tuple[list[tuple[int, int, int]], list[bytes]]:
    """Parse a SetMultiVariables request payload on the server side.

    Returns:
        Tuple of (items, values) where items is list of (db_number, byte_offset, byte_size)
        and values is list of raw bytes to write
    """
    pass
