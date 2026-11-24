"""Minimal OPC UA client: prints the simulator tags live in the terminal.

Usage (with opcua_server.py running in another window):
    python Pharmaceutical_MES/opcua_viewer.py
    python Pharmaceutical_MES/opcua_viewer.py --excursion on     # push the dryer temperature high
    python Pharmaceutical_MES/opcua_viewer.py --excursion off
    python Pharmaceutical_MES/opcua_viewer.py --count 10         # stop after 10 readings

Press Ctrl+C to stop. Values outside the alarm limits are marked "ALARM".
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime

from asyncua import Client, ua

import simulator

NAMESPACE = "urn:pharma-mes:simulator"


async def run(url: str, interval: float, count: int | None, excursion: str | None) -> None:
    async with Client(url) as client:
        idx = await client.get_namespace_index(NAMESPACE)
        nodes = {tag: client.get_node(ua.NodeId(tag, idx)) for tag in simulator.TAGS}
        exc_node = client.get_node(ua.NodeId("SIM/Excursion", idx))
        if excursion:
            await exc_node.write_value(excursion == "on")
            print(f"Excursion switched {excursion}")

        print(f"Connected to {url}\n")
        header = f"{'time':<10}" + "".join(f"{tag:>26}" for tag in simulator.TAGS)
        print(header)
        print("-" * len(header))
        n = 0
        while count is None or n < count:
            cells = []
            for tag, node in nodes.items():
                _, unit, lo, hi, _, _ = simulator.TAGS[tag]
                value = await node.read_value()
                flag = " ALARM" if not lo <= value <= hi else ""
                cells.append(f"{value:>14.2f} {unit:<5}{flag:<6}")
            print(f"{datetime.now():%H:%M:%S}  " + "".join(f"{c:>26}" for c in cells), flush=True)
            n += 1
            await asyncio.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Print live OPC UA tag values from opcua_server.py.")
    parser.add_argument("--url", default="opc.tcp://127.0.0.1:4840/pharma-mes/")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between readings")
    parser.add_argument("--count", type=int, help="number of readings (default: until Ctrl+C)")
    parser.add_argument("--excursion", choices=["on", "off"], help="switch the simulated excursion")
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)  # hide routine asyncua session warnings
    try:
        asyncio.run(run(args.url, args.interval, args.count, args.excursion))
    except KeyboardInterrupt:
        pass
    except (ConnectionError, OSError, asyncio.TimeoutError):
        raise SystemExit(f"Could not connect to {args.url}. Start the server first:\n"
                         "    python Pharmaceutical_MES/opcua_server.py")


if __name__ == "__main__":
    main()
