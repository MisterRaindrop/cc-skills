#!/usr/bin/env python3
"""Find the QD/QE processes of one session on THIS host, in THIS cluster only.

  qe_pids.py --con <gp_session_id> [--port 5432] [--db postgres]

Prints "pid label cmd" per process (label = sliceN or QD).

Why not just grep "con<N>": another cluster on the same host can have a session
with the same number.  A process is accepted only when
  1. its parent is a postmaster of this cluster: the pid in <datadir>/postmaster.pid
     of a gp_segment_configuration row, confirmed by /proc/<pid>/cwd == datadir;
  2. its command line carries "con<N>" as a whole word.
Read-only: one catalog query plus /proc reads.
"""
import argparse, os, re, subprocess, sys

CON_RX = re.compile(r"\bcon(\d+)\b")
SLICE_RX = re.compile(r"\bslice(-?\d+)\b")
CMD_RX = re.compile(r"\b(cmd\d+)\b")


def postmasters(port, db):
    """pid -> datadir of the postmasters of this cluster that run on this host."""
    r = subprocess.run(["psql", "-XAtq", "-p", str(port), "-d", db, "-c",
                        "select datadir from gp_segment_configuration where role = 'p'"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        sys.exit(f"qe_pids: cannot read gp_segment_configuration: {r.stderr.strip()}")
    pms = {}
    for dd in r.stdout.splitlines():
        dd = dd.strip()
        try:
            with open(os.path.join(dd, "postmaster.pid")) as f:
                pid = int(f.readline())
            if os.path.realpath(f"/proc/{pid}/cwd") == os.path.realpath(dd):
                pms[pid] = dd
        except (OSError, ValueError):
            pass                      # segment on another host, or not running
    if not pms:
        sys.exit("qe_pids: no postmaster of this cluster found on this host "
                 "(wrong port, or not the database OS user?)")
    return pms


def stat_fields(pid):
    """Fields after the ')' of /proc/<pid>/stat; index 0 = field 3 (state)."""
    with open(f"/proc/{pid}/stat") as f:
        s = f.read()
    return s[s.rfind(")") + 2:].split()


def find(con, pms):
    """[(pid, label, cmd, cmdline)] of session `con` under the given postmasters."""
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            if int(stat_fields(d)[1]) not in pms:          # field 4 = ppid
                continue
            with open(f"/proc/{d}/cmdline", "rb") as f:
                cl = f.read().decode(errors="ignore").replace("\0", " ")
        except (OSError, IndexError, ValueError):
            continue
        m = CON_RX.search(cl)
        if not m or m.group(1) != str(con):
            continue
        s = SLICE_RX.search(cl)
        c = CMD_RX.search(cl)
        # QEs carry "segN"; a QE between statements has no slice -> "idle".
        lab = f"slice{s.group(1)}" if s else ("idle" if re.search(r"\bseg\d+\b", cl) else "QD")
        out.append((int(d), lab, c.group(1) if c else "-", cl))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--con", required=True, type=int)
    ap.add_argument("--port", default=os.environ.get("PGPORT", "5432"))
    ap.add_argument("--db", default=os.environ.get("PGDATABASE", "postgres"))
    a = ap.parse_args()
    for pid, label, cmd, _ in sorted(find(a.con, postmasters(a.port, a.db)), key=lambda x: x[1]):
        print(pid, label, cmd)
