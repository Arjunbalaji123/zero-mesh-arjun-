import asyncio
import base64
import json
import struct
import uuid
from typing import Any, Dict, Optional, Tuple


class MessageType:
    PING = "PING"
    PONG = "PONG"
    STORE_CHUNK = "STORE_CHUNK"
    GET_CHUNK = "GET_CHUNK"
    FIND_NODE = "FIND_NODE"
    FIND_VALUE = "FIND_VALUE"
    HEARTBEAT = "HEARTBEAT"
    RESPONSE = "RESPONSE"
    ERROR = "ERROR"


def create_message(
    msg_type: str,
    sender_id: str,
    sender_ip: str,
    sender_port: int,
    payload: Optional[Dict[str, Any]] = None,
    msg_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "msg_type": msg_type,
        "sender_id": sender_id,
        "sender_ip": sender_ip,
        "sender_port": sender_port,
        "msg_id": msg_id or str(uuid.uuid4()),
        "payload": payload or {},
    }


async def send_framed_message(
    writer: asyncio.StreamWriter, message: Dict[str, Any]
) -> None:
    """Encodes JSON message and sends it over TCP with a 4-byte length header."""
    json_bytes = json.dumps(message).encode("utf-8")
    length_prefix = struct.pack("!I", len(json_bytes))
    writer.write(length_prefix + json_bytes)
    await writer.drain()


async def read_framed_message(
    reader: asyncio.StreamReader, timeout: float = 5.0
) -> Optional[Dict[str, Any]]:
    """Reads length-prefixed JSON message from TCP stream."""
    try:
        header = await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
        length = struct.unpack("!I", header)[0]
        data = await asyncio.wait_for(reader.readexactly(length), timeout=timeout)
        return json.loads(data.decode("utf-8"))
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionResetError):
        return None
    except Exception as e:
        return None


async def send_rpc_request(
    ip: str,
    port: int,
    message: Dict[str, Any],
    timeout: float = 5.0,
    retries: int = 1,
) -> Optional[Dict[str, Any]]:
    """Connects to target peer, sends RPC request, and returns response with retry logic."""
    for attempt in range(retries + 1):
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=timeout
            )
            await send_framed_message(writer, message)
            response = await read_framed_message(reader, timeout=timeout)
            writer.close()
            await writer.wait_closed()
            if response:
                return response
        except Exception:
            if attempt == retries:
                return None
            await asyncio.sleep(0.2)
    return None
