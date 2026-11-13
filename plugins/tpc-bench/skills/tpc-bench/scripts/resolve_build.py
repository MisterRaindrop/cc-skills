#!/usr/bin/env python3
"""Resolve an umbrella CI build to package URLs (runs locally, needs glab logged in to TPCBENCH_GITLAB_HOST, see site.env.example).

usage: resolve_build.py <latest|PIPELINE_ID> [--arch aarch64|x86_64] [--ref main]
prints one JSON object: pipeline, sha, title, created_at, arch, job_id, rpm_url, release_yaml_url,
version_tag, ci_jobs {name: status} (test results of the same pipeline, for the record).
"""
import json, os, subprocess, sys, argparse, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tpcsite

PROJECT = urllib.parse.quote(tpcsite.get("TPCBENCH_UMBRELLA_PROJECT"), safe="")
ENV = dict(os.environ, GITLAB_HOST=tpcsite.get("TPCBENCH_GITLAB_HOST"))


def api(path):
    out = subprocess.run(["glab", "api", path], env=ENV, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"glab api {path} failed: {out.stderr.strip()[:300]}")
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return out.stdout


def jobs_of(pid):
    return api(f"projects/{PROJECT}/pipelines/{pid}/jobs?per_page=100&include_retried=false")


def build_job(jobs, arch):
    name = f"build_database: [{arch}]"
    ok = [j for j in jobs if j["name"] == name and j["status"] == "success"]
    return ok[0] if ok else None


def between(lo, hi, arch, ref):
    """Push pipelines on ref with lo < id <= hi that have a successful build job, oldest first (for bisecting).
    Each entry: pipeline, created_at, sha, artifacts (whether the manifest is still downloadable)."""
    out, page = [], 1
    while page < 20:
        ps = api(f"projects/{PROJECT}/pipelines?ref={ref}&source=push&per_page=100&page={page}")
        if not ps:
            break
        for p in ps:
            if lo < p["id"] <= hi:
                j = build_job(jobs_of(p["id"]), arch)
                if j:
                    m = api(f"projects/{PROJECT}/jobs/{j['id']}/artifacts/dist/packages/manifest-{arch}.txt")
                    out.append(dict(pipeline=p["id"], created_at=p["created_at"], sha=p["sha"],
                                    artifacts=isinstance(m, str) and "db_rpm_url=" in m))
        if min(p["id"] for p in ps) <= lo:
            break
        page += 1
    return sorted(out, key=lambda x: x["pipeline"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build", help="latest | PIPELINE | between:LO:HI (list pipelines LO<id<=HI)")
    ap.add_argument("--arch", default="aarch64")
    ap.add_argument("--ref", default="main")
    a = ap.parse_args()

    if a.build.startswith("between:"):
        _, lo, hi = a.build.split(":")
        print(json.dumps(between(int(lo), int(hi), a.arch, a.ref)))
        return
    if a.build == "latest":
        cands = api(f"projects/{PROJECT}/pipelines?ref={a.ref}&source=push&per_page=20")
        pid, jobs, job = None, None, None
        for p in cands:
            js = jobs_of(p["id"])
            j = build_job(js, a.arch)
            if j:
                pid, jobs, job = p["id"], js, j
                break
        if not pid:
            sys.exit(f"no push pipeline on {a.ref} in the last 20 with a successful build_database [{a.arch}]")
    else:
        pid = int(a.build)
        jobs = jobs_of(pid)
        job = build_job(jobs, a.arch)
        if not job:
            sys.exit(f"pipeline {pid}: no successful build_database [{a.arch}] job")

    p = api(f"projects/{PROJECT}/pipelines/{pid}")
    manifest = api(f"projects/{PROJECT}/jobs/{job['id']}/artifacts/dist/packages/manifest-{a.arch}.txt")
    if not isinstance(manifest, str) or "db_rpm_url=" not in manifest:
        sys.exit(f"job {job['id']}: manifest-{a.arch}.txt not readable (artifacts expire after 1 week)")
    kv = dict(l.split("=", 1) for l in manifest.splitlines() if "=" in l)
    commit = api(f"projects/{PROJECT}/repository/commits/{p['sha']}")
    print(json.dumps({
        "pipeline": pid, "sha": p["sha"], "ref": p["ref"], "title": commit.get("title", ""),
        "created_at": p["created_at"], "arch": a.arch, "job_id": job["id"],
        "version_tag": kv.get("version_tag"), "rpm_url": kv["db_rpm_url"],
        "release_yaml_url": kv.get("release_yaml_url"),
        "ci_jobs": {j["name"]: j["status"] for j in jobs},
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
