import asyncio
import pytest
from app.network.protocol import (
    MessageType,
    create_message,
    send_framed_message,
    read_framed_message,
    send_rpc_request,
)
from app.storage.local_store import LocalChunkStore


@pytest.mark.asyncio
async def test_tcp_protocol_roundtrip(tmp_path):
    server_port = 9876
    node_id = "test_node_1"

    async def handle_client(reader, writer):
        msg = await read_framed_message(reader)
        assert msg is not None
        assert msg["msg_type"] == MessageType.PING

        response = create_message(
            msg_type=MessageType.PONG,
            sender_id=node_id,
            sender_ip="127.0.0.1",
            sender_port=server_port,
            payload={"status": "ok"},
            msg_id=msg["msg_id"],
        )
        await send_framed_message(writer, response)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", server_port)

    # Client send
    ping_msg = create_message(
        msg_type=MessageType.PING,
        sender_id="client_node",
        sender_ip="127.0.0.1",
        sender_port=9877,
    )
    res = await send_rpc_request("127.0.0.1", server_port, ping_msg)

    assert res is not None
    assert res["msg_type"] == MessageType.PONG
    assert res["payload"]["status"] == "ok"

    server.close()
    await server.wait_closed()


def test_local_chunk_store(tmp_path):
    store = LocalChunkStore("test_node", base_dir=tmp_path)
    chunk_id = "chunk_123"
    data = b"Encrypted chunk data bytes"

    assert not store.has_chunk(chunk_id)
    assert store.store_chunk(chunk_id, data)
    assert store.has_chunk(chunk_id)

    read_bytes = store.get_chunk(chunk_id)
    assert read_bytes == data

    assert store.delete_chunk(chunk_id)
    assert not store.has_chunk(chunk_id)
