#!/usr/bin/env python3
"""Coherence audit — verify world state mutations propagate between turns.

Queries ClickHouse for consecutive turn traces, compares extraction output
(found world_changes) against next-turn context input (actual location ID).
Flags any turn where the narrative claims a change but the world disagrees.

Usage:
    uv run python scripts/audit_coherence.py --hours 4
    uv run python scripts/audit_coherence.py --hours 4 --json
"""

import json
import re
import subprocess
import sys
from collections import defaultdict
from typing import TypedDict

CK = [
    "podman",
    "exec",
    "infra-data-clickhouse",
    "clickhouse-client",
    "--user",
    "langfuse",
    "--password",
    "langfuse",
    "--query",
]
PROJECT = "cmonj12g70006guxy9z6qo25g"


class ObservationPayload(TypedDict):
    input: str
    output: str


class ObservationRow(TypedDict):
    generation: ObservationPayload | None
    extraction: ObservationPayload | None
    ts: str | None
    session: str | None


def clickhouse(query: str) -> str:
    cmd = CK + [query]
    return subprocess.check_output(cmd, text=True, stderr=subprocess.PIPE)


def get_observations(project: str, hours: int = 4) -> dict[str, ObservationRow]:
    """Fetch generation + extraction observations grouped by trace."""
    raw = clickhouse(f"""
        SELECT t.id, t.timestamp, o.name, o.input, o.output, t.session_id
        FROM default.observations o
        JOIN default.traces t ON o.trace_id = t.id
        WHERE o.project_id = '{project}'
          AND t.timestamp > now() - INTERVAL {hours} HOUR
          AND o.name IN ('pipeline.generation', 'pipeline.extraction')
        ORDER BY t.session_id, t.timestamp, o.name
    """)

    results: defaultdict[str, ObservationRow] = defaultdict(
        lambda: {
            "generation": None,
            "extraction": None,
            "ts": None,
            "session": None,
        }
    )
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t", 5)
        if len(parts) < 6:
            continue
        tid, ts, name, inp, out, sid = parts
        key = name.split(".")[-1]  # "generation" or "extraction"
        results[tid]["ts"] = ts
        results[tid]["session"] = sid
        results[tid][key] = {"input": inp, "output": out}
    return results


def extract_location_id(gen_input: str) -> str | None:
    """Parse world context from generation input, return location ID."""
    # Find "location" JSON key (with escaped quotes in ClickHouse output)
    # followed by its nested "id" field containing a UUID
    match = re.search(
        r'"location".{0,200}?"id"[^a-f0-9]*([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})',
        gen_input,
    )
    if match:
        return match.group(1)
    return None


def extract_world_changes(ext_output: str) -> list[dict]:
    """Parse extraction output for world_changes."""
    clean = ext_output.strip()
    # Strip markdown
    if clean.startswith("```"):
        clean = clean[clean.find("\n") + 1 :] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
    elif clean.startswith("json\n"):
        clean = clean[5:]
    clean = clean.strip()
    try:
        data = json.loads(clean)
        return data.get("world_changes", [])
    except json.JSONDecodeError:
        return []


def audit(hours: int = 4) -> dict:
    obs = get_observations(PROJECT, hours=hours)
    sessions = defaultdict(list)

    for tid, data in obs.items():
        generation = data["generation"]
        extraction = data["extraction"]
        session_id = data["session"]
        ts = data["ts"]
        if generation is None or extraction is None or session_id is None or ts is None:
            continue
        sessions[session_id].append(
            {
                "trace_id": tid[:8],
                "ts": ts,
                "location_id": extract_location_id(generation["input"]),
                "location_changes": [
                    c
                    for c in extract_world_changes(extraction["output"])
                    if c.get("attribute") == "location"
                ],
            }
        )

    findings = {"sessions_checked": 0, "turns_checked": 0, "violations": []}
    for sid, turns in sorted(sessions.items()):
        if len(turns) < 2:
            continue
        findings["sessions_checked"] += 1
        turns.sort(key=lambda t: t["ts"])

        for i in range(len(turns) - 1):
            findings["turns_checked"] += 1
            cur, nxt = turns[i], turns[i + 1]

            if not cur["location_changes"]:
                continue  # nothing claimed, nothing to verify

            # Check: did the location actually change?
            if cur["location_id"] and nxt["location_id"]:
                if cur["location_id"] == nxt["location_id"]:
                    claimed = cur["location_changes"][0].get("new_value", "?")
                    findings["violations"].append(
                        {
                            "session": sid,
                            "turn_n": cur["trace_id"],
                            "turn_n+1": nxt["trace_id"],
                            "claimed": claimed,
                            "stuck_at": cur["location_id"][:12],
                            "issue": (
                                f"Extraction claims '{claimed}' but location "
                                f"unchanged: {cur['location_id'][:12]}"
                            ),
                        }
                    )

    return findings


def main():
    import argparse

    p = argparse.ArgumentParser(description="TTA coherence audit")
    p.add_argument("--hours", type=int, default=4)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    f = audit(hours=args.hours)

    if args.json:
        print(json.dumps(f, indent=2))
        return 0 if not f["violations"] else 1

    print(f"Coherence Audit (last {args.hours}h)")
    print(f"  Sessions: {f['sessions_checked']}")
    print(f"  Turn pairs: {f['turns_checked']}")
    print(f"  Violations: {len(f['violations'])}")
    print()

    if f["violations"]:
        for v in f["violations"]:
            print(f"  Session {v['session'][:16]}")
            print(f"    {v['turn_n']} → {v['turn_n+1']}")
            print(f"    {v['issue']}")
            print()
        return 1

    print("No violations — world state is consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
