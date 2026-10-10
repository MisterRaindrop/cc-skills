#!/usr/bin/env python3
"""Watch GitLab merge requests and exit on the first event worth acting on.

Usage: watch_mr.py HOST PROJECT IID [IID ...]

  HOST     GitLab host, e.g. gitlab.example.com
  PROJECT  project path, e.g. group/subgroup/repo
  IID      merge request IIDs to watch

Events (one line each on stdout, then exit 0):
  MERGED / CLOSED      the MR left the opened state
  HEAD_MOVED           the source branch HEAD changed
  JOB_FAILED           a job that may not fail failed in the HEAD's pipeline
  PIPELINE_DONE        the HEAD's latest pipeline reached a final status
  NO_PIPELINE          the HEAD has no pipeline
  TIMEOUT              nothing happened within MAX_SECONDS

Environment: GITLAB_TOKEN (else `glab config get token --host HOST`),
INTERVAL seconds between polls (default 300), MAX_SECONDS before TIMEOUT
(default 6600, under a two-hour background-task limit).

The token is only sent to HOST and never printed.
"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

FINAL = {"success", "failed", "canceled", "skipped"}


def token(host):
    tok = os.environ.get("GITLAB_TOKEN")
    if tok:
        return tok
    return subprocess.run(["glab", "config", "get", "token", "--host", host],
                          capture_output=True, text=True, check=True).stdout.strip()


def api(host, tok, path):
    req = urllib.request.Request(f"https://{host}/api/v4/{path}",
                                 headers={"PRIVATE-TOKEN": tok})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def snapshot(host, tok, proj, iid):
    mr = api(host, tok, f"projects/{proj}/merge_requests/{iid}")
    pipes = api(host, tok, f"projects/{proj}/merge_requests/{iid}/pipelines?per_page=5")
    pipe = next((p for p in pipes if p["sha"] == mr["sha"]), None)
    failed = set()
    if pipe:
        jobs = api(host, tok, f"projects/{proj}/pipelines/{pipe['id']}/jobs?per_page=100")
        failed = {f"{j['id']} {j['name']} ({j.get('failure_reason')})"
                  for j in jobs if j["status"] == "failed" and not j["allow_failure"]}
    return {"state": mr["state"], "sha": mr["sha"],
            "pipe": pipe and (pipe["id"], pipe["status"]), "failed": failed}


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    host, proj, iids = sys.argv[1], urllib.parse.quote(sys.argv[2], safe=""), sys.argv[3:]
    interval = int(os.environ.get("INTERVAL", "300"))
    deadline = time.time() + int(os.environ.get("MAX_SECONDS", "6600"))
    tok = token(host)
    base = {}
    while True:
        events = []
        for iid in iids:
            try:
                cur = snapshot(host, tok, proj, iid)
            except Exception as exc:  # transient API failure: try again next round
                print(f"!{iid} poll error: {exc}", file=sys.stderr)
                continue
            old = base.setdefault(iid, cur)
            tag = f"!{iid} {cur['sha'][:9]}"
            if cur["state"] != "opened":
                events.append(f"{cur['state'].upper()} {tag}")
            elif cur["sha"] != old["sha"]:
                events.append(f"HEAD_MOVED {tag} (was {old['sha'][:9]})")
            elif cur["pipe"] is None:
                events.append(f"NO_PIPELINE {tag}")
            elif cur["pipe"][1] in FINAL:
                events.append(f"PIPELINE_DONE {tag} pipeline {cur['pipe'][0]} {cur['pipe'][1]}")
            else:
                for job in sorted(cur["failed"] - old["failed"]):
                    events.append(f"JOB_FAILED {tag} pipeline {cur['pipe'][0]} job {job}")
            # A finished or failing pipeline is reported once; the caller re-arms.
            base[iid] = cur
        if events:
            print("\n".join(events), flush=True)
            return
        if time.time() >= deadline:
            print(f"TIMEOUT no event for {' '.join('!' + i for i in iids)}", flush=True)
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
