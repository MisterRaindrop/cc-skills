#!/usr/bin/env python3
"""Read-only host discovery (run as root on the target: ssh host python3 - < discover.py [workdir_marker_name]).
Prints JSON: hardware, disks, every postmaster (port, datadir, user, container?, tpcbench-owned?),
gpfdist processes, and the CPU used by postgres processes during a 3s window (busy check)."""
import json, os, re, socket, subprocess, time, platform

MARKER = ".tpcbench_cluster"


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def read(p, default=""):
    try:
        with open(p) as f:
            return f.read()
    except Exception:
        return default


def procs():
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            stat = read(f"/proc/{d}/stat")
            comm = stat[stat.index("(") + 1:stat.rindex(")")]
            rest = stat[stat.rindex(")") + 2:].split()
            ppid = int(rest[1]); cpu = int(rest[11]) + int(rest[12])
            cmd = read(f"/proc/{d}/cmdline").replace("\0", " ").strip()
            uid = int(re.search(r"Uid:\s+(\d+)", read(f"/proc/{d}/status")).group(1))
            out.append(dict(pid=int(d), ppid=ppid, comm=comm, cmd=cmd, cpu=cpu, uid=uid))
        except Exception:
            pass
    return out


def host_cpu():
    """user nice system idle iowait irq softirq steal (jiffies, all CPUs)"""
    for l in open("/proc/stat"):
        if l.startswith("cpu "):
            return [int(x) for x in l.split()[1:9]]


def in_container(pid):
    try:
        return os.stat(f"/proc/{pid}/root").st_ino != os.stat("/").st_ino or \
            "docker" in read(f"/proc/{pid}/cgroup") or "containerd" in read(f"/proc/{pid}/cgroup")
    except Exception:
        return None


def main():
    ps = procs()
    byppid = {}
    for p in ps:
        byppid.setdefault(p["ppid"], []).append(p)
    pms = []
    for p in ps:
        if p["comm"] not in ("postgres", "postmaster"):
            continue
        m = re.search(r"-D\s+(\S+)", p["cmd"])
        if not m:
            continue
        parent = next((q for q in ps if q["pid"] == p["ppid"]), None)
        if parent and parent["comm"] in ("postgres", "postmaster") and "-D" in parent["cmd"]:
            continue
        datadir = m.group(1)
        port = re.search(r"-p\s+(\d+)", p["cmd"])
        cont = in_container(p["pid"])
        root = f"/proc/{p['pid']}/root" if cont else ""
        if not port:
            pf = read(f"{root}{datadir}/postmaster.pid").splitlines()
            port = pf[3] if len(pf) > 3 else None
        else:
            port = port.group(1)
        conf = read(f"{root}{datadir}/postgresql.conf")
        content = re.search(r"^\s*gp_contentid\s*=\s*(-?\d+)", conf, re.M)
        if content is None:
            ic = read(f"{root}{datadir}/internal.auto.conf")
            content = re.search(r"gp_contentid\s*=\s*'?(-?\d+)", ic)
        pms.append(dict(pid=p["pid"], port=int(port) if port else None, datadir=datadir,
                        user=p["uid"], container=cont, content=int(content.group(1)) if content else None,
                        tpcbench=os.path.exists(f"{root}{datadir}/{MARKER}") or os.path.exists(
                            os.path.join(os.path.dirname(os.path.dirname(datadir)), MARKER)),
                        nchildren=len(byppid.get(p["pid"], []))))
    # CPU busy check over 3 seconds.
    # Host level from /proc/stat (counts short-lived QEs too: every query forks new ones, so per-process deltas
    # between two snapshots miss most of a running benchmark). Per postmaster port: best effort from processes
    # alive in both snapshots, taken right around the sleep.
    WIN = 3
    st0 = host_cpu(); c0 = {p["pid"]: p["cpu"] for p in procs()}
    time.sleep(WIN)
    st1 = host_cpu(); ps2 = procs()
    hz = os.sysconf("SC_CLK_TCK")
    tot = sum(st1) - sum(st0)
    host_busy = round((1 - (st1[3] + st1[4] - st0[3] - st0[4]) / tot) * (os.cpu_count() or 1), 1) if tot else None
    pmpids = {pm["pid"]: pm for pm in pms}
    parent = {p["pid"]: p["ppid"] for p in ps2}
    busy = {}
    for p in ps2:
        if p["pid"] not in c0:
            continue
        d = (p["cpu"] - c0[p["pid"]]) / hz / WIN
        if d <= 0:
            continue
        q, pm = p["pid"], None
        for _ in range(3):                      # backend -> postmaster (QE/QD are direct children)
            if q in pmpids:
                pm = pmpids[q]; break
            q = parent.get(q)
        key = f"port{pm['port']}" if pm else ("other:" + p["comm"])
        busy[key] = busy.get(key, 0) + d
    mem = dict(re.findall(r"^(\w+):\s+(\d+)", read("/proc/meminfo"), re.M))
    disks = []
    for line in sh("df -B1 --output=target,size,avail,source -x tmpfs -x devtmpfs -x overlay").splitlines()[1:]:
        t, s, a, src = line.split()[:4]
        if t.startswith("/data") or t == "/":
            disks.append(dict(mount=t, size_gb=int(s) // 2**30, avail_gb=int(a) // 2**30, dev=src))
    osr = dict(re.findall(r'^(\w+)="?([^"\n]*)"?', read("/etc/os-release"), re.M))
    print(json.dumps(dict(
        hostname=socket.gethostname().split(".")[0], ip=sh("hostname -I").split()[0] if sh("hostname -I") else "",
        arch=platform.machine(), cores=os.cpu_count(),
        cpu_model=sh("lscpu | awk -F: '/Model name/{print $2; exit}'").strip(),
        mem_gb=int(mem["MemTotal"]) // 2**20, mem_avail_gb=int(mem["MemAvailable"]) // 2**20,
        os=f"{osr.get('PRETTY_NAME', '')} {platform.machine()}", kernel=platform.release(),
        thp=read("/sys/kernel/mm/transparent_hugepage/enabled").strip(),
        loadavg=read("/proc/loadavg").split()[:3], disks=disks,
        nvme_count=len([d for d in os.listdir("/sys/block") if d.startswith("nvme")]),
        postmasters=sorted(pms, key=lambda x: (x["port"] or 0)),
        gpfdist=[dict(pid=p["pid"], uid=p["uid"], cmd=p["cmd"][:160]) for p in ps if p["comm"] == "gpfdist"],
        host_busy_cores=host_busy,
        postgres_cores_busy={k: round(v, 2) for k, v in sorted(busy.items(), key=lambda kv: -kv[1])
                             if k.startswith("port") or v >= 0.5},
        gpadmin_sudo=sh("su - gpadmin -c 'sudo -n true' >/dev/null 2>&1 && echo yes || echo no"),
    ), ensure_ascii=False))


if __name__ == "__main__":
    main()
