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
