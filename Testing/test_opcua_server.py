"""The OPC UA server publishes the simulator tags and honours the excursion switch."""
import asyncio
import types

from asyncua import Client, ua

import opcua_server
import simulator

PORT = 48401  # not the default, so a running demo server does not interfere


async def _exercise():
    args = types.SimpleNamespace(host="127.0.0.1", port=PORT, log_batch=None, log_every=60)
    task = asyncio.create_task(opcua_server.run(args))
    await asyncio.sleep(2)
    try:
        async with Client(f"opc.tcp://127.0.0.1:{PORT}/pharma-mes/") as client:
            idx = await client.get_namespace_index(opcua_server.NAMESPACE)
            readings = {}
            for tag in simulator.TAGS:
                readings[tag] = await client.get_node(ua.NodeId(tag, idx)).read_value()
            await client.get_node(ua.NodeId("SIM/Excursion", idx)).write_value(True)
            await asyncio.sleep(2.5)
            hot = await client.get_node(ua.NodeId(opcua_server.EXCURSION_TAG, idx)).read_value()
            await client.get_node(ua.NodeId("SIM/Excursion", idx)).write_value(False)
        return readings, hot
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_tags_are_published_and_excursion_breaches_limit():
    readings, hot = asyncio.run(_exercise())
    for tag, (_, _, lo, hi, _, _) in simulator.TAGS.items():
        assert lo <= readings[tag] <= hi, (tag, readings[tag])
    assert hot > simulator.TAGS[opcua_server.EXCURSION_TAG][3]  # above the 70 degC alarm limit


async def _log_excursion(batch_no):
    args = types.SimpleNamespace(host="127.0.0.1", port=PORT + 1, log_batch=batch_no, log_every=1)
    task = asyncio.create_task(opcua_server.run(args))
    await asyncio.sleep(2)
    try:
        async with Client(f"opc.tcp://127.0.0.1:{PORT + 1}/pharma-mes/") as client:
            idx = await client.get_namespace_index(opcua_server.NAMESPACE)
            await client.get_node(ua.NodeId("SIM/Excursion", idx)).write_value(True)
            await asyncio.sleep(3)
            await client.get_node(ua.NodeId("SIM/Excursion", idx)).write_value(False)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_logged_excursion_raises_a_deviation_on_the_batch(conn, new_batch, monkeypatch):
    import db
    monkeypatch.setattr(db, "connect", lambda *a, **k: conn)  # log to the test database
    batch_no = conn.execute("SELECT batch_no FROM batches WHERE batch_id = %s", (new_batch,)).fetchone()[0]
    asyncio.run(_log_excursion(batch_no))
    assert conn.execute("SELECT count(*) FROM process_signals WHERE batch_id = %s", (new_batch,)).fetchone()[0] > 0
    devs = conn.execute("SELECT description FROM deviations WHERE batch_id = %s AND source = 'PROCESS_SIGNAL'",
                        (new_batch,)).fetchall()
    assert len(devs) == 1 and devs[0][0].startswith(opcua_server.EXCURSION_TAG)
