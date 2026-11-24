"""Simulated DCS process signals with DeltaV-style tag names.

This is NOT a connection to a real DeltaV system, OPC UA server or historian.
It generates plausible values (a mean-reverting random walk around a setpoint)
so the MES can show process data next to the batch record. An optional
excursion pushes one tag past its alarm limit, which makes the database raise
a deviation.

Usage:
    python Pharmaceutical_MES/simulator.py PCM-500-0011 --minutes 30
    python Pharmaceutical_MES/simulator.py PCM-500-0011 --minutes 30 --excursion
"""
from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta, timezone

# tag: (description, unit, low alarm, high alarm, setpoint, noise)
TAGS = {
    "GRAN-101/TIC-101/PV.CV": ("Granulator bed temperature", "degC", 20, 45, 32.0, 0.6),
    "GRAN-101/SIC-102/PV.CV": ("Granulator impeller speed", "rpm", 150, 250, 200.0, 4.0),
    "FBD-201/TIC-201/PV.CV": ("Fluid bed dryer inlet air temperature", "degC", 55, 70, 62.0, 0.5),
    "FBD-201/MT-202/PV.CV": ("Fluid bed dryer exhaust humidity", "%RH", 10, 40, 24.0, 1.0),
}


def tag_limit_rows() -> list[tuple]:
    return [(tag, d, u, lo, hi) for tag, (d, u, lo, hi, _, _) in TAGS.items()]


def generate(start: datetime, minutes: int = 60, interval_s: int = 60, seed: int | None = None,
             excursion: tuple[str, int, int, float] | None = None) -> list[tuple[str, float, datetime]]:
    """Return (tag, value, timestamp) rows.

    excursion = (tag, start minute, duration in minutes, offset added to the value)
    """
    rng = random.Random(seed)
    rows = []
    for tag, (_, _, _, _, sp, noise) in TAGS.items():
        value = sp + rng.gauss(0, noise)
        for i in range(minutes * 60 // interval_s):
            value += 0.3 * (sp - value) + rng.gauss(0, noise)  # mean-reverting walk
            minute = i * interval_s / 60
            v = value
            if excursion and excursion[0] == tag and excursion[1] <= minute < excursion[1] + excursion[2]:
                v += excursion[3]
            rows.append((tag, v, start + timedelta(seconds=i * interval_s)))
    return rows


def default_excursion(rng: random.Random | None = None) -> tuple[str, int, int, float]:
    rng = rng or random.Random()
    return ("FBD-201/TIC-201/PV.CV", rng.randint(5, 15), 4, 11.0)


def main() -> None:
    import db
    import mes

    parser = argparse.ArgumentParser(description="Write simulated process signals for a batch.")
    parser.add_argument("batch_no")
    parser.add_argument("--minutes", type=int, default=30)
    parser.add_argument("--excursion", action="store_true", help="push the dryer inlet temperature above its limit")
    args = parser.parse_args()

    with db.connect() as conn:
        row = conn.execute("SELECT batch_id FROM batches WHERE batch_no = %s", (args.batch_no,)).fetchone()
        if not row:
            raise SystemExit(f"Batch {args.batch_no} not found")
        start = datetime.now(timezone.utc) - timedelta(minutes=args.minutes)
        rows = generate(start, args.minutes, excursion=default_excursion() if args.excursion else None)
        mes.add_signals(conn, row[0], rows)
        print(f"Wrote {len(rows)} signal values for {args.batch_no}")


if __name__ == "__main__":
    main()
