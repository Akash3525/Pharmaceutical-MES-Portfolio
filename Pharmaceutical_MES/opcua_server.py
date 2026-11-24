"""OPC UA server for the simulated DeltaV-style process tags.

Usage:
    python Pharmaceutical_MES/opcua_server.py
    python Pharmaceutical_MES/opcua_server.py --log-batch PCM-500-0007 --log-every 60

Publishes the four simulator tags on opc.tcp://localhost:4840/pharma-mes/ so
any OPC UA client (Ignition, UaExpert, ...) can browse and subscribe to them.
Values update every second with the same mean-reverting walk as simulator.py.

Writable control tags (ns=2):
    SIM/Excursion   (Boolean)  true pushes the dryer inlet temperature +11 degC
    SIM/ActiveBatch (String)   batch number shown to clients

With --log-batch, values are also written to the process_signals table every
--log-every seconds, so excursions raise deviations through the same database
trigger as the rest of the MES.

This is a simulation for learning purposes: no real DCS is involved. Security is
off (anonymous, no encryption) because it only listens on this computer.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import random
from datetime import datetime, timezone

from asyncua import Server, ua

import simulator

NAMESPACE = "urn:pharma-mes:simulator"
EXCURSION_TAG = "FBD-201/TIC-201/PV.CV"
EXCURSION_OFFSET = 11.0

log = logging.getLogger("opcua_server")


async def build_server(host: str = "127.0.0.1", port: int = 4840) -> tuple[Server, dict, object, object]:
    server = Server()
    await server.init()
    server.set_endpoint(f"opc.tcp://{host}:{port}/pharma-mes/")
    server.set_server_name("Pharma MES DeltaV Simulator")
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
    idx = await server.register_namespace(NAMESPACE)

    root = await server.nodes.objects.add_folder(ua.NodeId("DeltaV", idx), "DeltaV")
    variables = {}
    for tag, (desc, unit, lo, hi, sp, _) in simulator.TAGS.items():
        module = tag.split("/")[0]
        folder = variables.get(("folder", module))
        if folder is None:
            folder = await root.add_folder(ua.NodeId(f"DeltaV/{module}", idx), module)
            variables[("folder", module)] = folder
        var = await folder.add_variable(ua.NodeId(tag, idx), tag.split("/", 1)[1], float(sp),
                                        varianttype=ua.VariantType.Double)
        await var.write_attribute(ua.AttributeIds.Description, ua.DataValue(
            ua.Variant(ua.LocalizedText(f"{desc} [{unit}], alarm limits {lo}-{hi}"), ua.VariantType.LocalizedText)))
        variables[tag] = var

    sim = await server.nodes.objects.add_folder(ua.NodeId("SIM", idx), "SIM")
    excursion = await sim.add_variable(ua.NodeId("SIM/Excursion", idx), "Excursion", False,
                                       varianttype=ua.VariantType.Boolean)
    batch = await sim.add_variable(ua.NodeId("SIM/ActiveBatch", idx), "ActiveBatch", "",
                                   varianttype=ua.VariantType.String)
    await excursion.set_writable()
    await batch.set_writable()
    return server, {k: v for k, v in variables.items() if isinstance(k, str)}, excursion, batch


async def run(args) -> None:
    server, tags, excursion, batch = await build_server(args.host, args.port)
    rng = random.Random()
    values = {tag: sp for tag, (_, _, _, _, sp, _) in simulator.TAGS.items()}

    conn = batch_id = None
    if args.log_batch:
        import db
        import mes
        conn = db.connect()
        row = conn.execute("SELECT batch_id FROM batches WHERE batch_no = %s", (args.log_batch,)).fetchone()
        if not row:
            raise SystemExit(f"Batch {args.log_batch} not found")
        batch_id = row[0]
        await batch.write_value(args.log_batch)

    async with server:
        log.info("OPC UA server listening on opc.tcp://%s:%s/pharma-mes/", args.host, args.port)
        tick = 0
        while True:
            exc_on = await excursion.read_value()
            now = datetime.now(timezone.utc)
            rows = []
            for tag, (_, _, _, _, sp, noise) in simulator.TAGS.items():
                values[tag] += 0.3 * (sp - values[tag]) + rng.gauss(0, noise)
                v = values[tag] + (EXCURSION_OFFSET if exc_on and tag == EXCURSION_TAG else 0.0)
                await tags[tag].write_value(round(v, 3))
                rows.append((tag, v, now))
            if conn is not None and tick % args.log_every == 0:
                try:
                    mes.add_signals(conn, batch_id, rows)
                except Exception as exc:  # keep serving tags even if the database write fails
                    log.warning("could not log signals: %s", exc)
            tick += 1
            await asyncio.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="OPC UA server for simulated DeltaV-style tags.")
    parser.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to accept other computers")
    parser.add_argument("--port", type=int, default=4840)
    parser.add_argument("--log-batch", help="batch number whose process_signals receive the values")
    parser.add_argument("--log-every", type=int, default=60, help="seconds between database writes")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("asyncua").setLevel(logging.WARNING)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
