#!/usr/bin/env python3
"""mkconfig.py <workdir> <cluster> <set h|ds> <scale> <mode load|run> [--tags "..."] [--upload true|false]
                [--vec on|off] [--pipeline off|on] [--guc name=value ...] [--pre-sql "..."]
Writes a proteus config under <workdir>/proteus/configs/<config>/ and the proteus ENV file for the cluster,
filled from cluster.json + host.json (discovery). Prints the config name.
Schema / role names are derived from scale+AM so data of different scales never collide:
  schema  sf<scale><am>[rand]_tpch / _tpcds      role  hbench_sf<scale><am>[rand] / dsbench_...
  Distribution defaults to hash (proteus default, RANDOM_DISTRIBUTION=false); --random true gives the [rand] variant.
  --pipeline on (vector.enable_vec_pipeline) is a separate config "<...>_run_pipe": it is written explicitly into guc.conf
  (proteus applies guc.conf cluster-wide and it persists, so "off" must be explicit too) and into PRE_QUERY_SQL (deep.py
  replays the query with the run's PRE_QUERY_SQL, so phase 2 uses the same mode whatever the cluster was left on)."""
import argparse, json, os

GUC_BASE = """optimizer=on
optimizer_analyze_root_partition=on|masteronly
gp_autostats_mode=none|masteronly
default_statistics_target=100
gp_vmem_protect_limit=15000
max_statement_mem=14GB
statement_mem=6GB
gp_fts_probe_timeout=600
gp_fts_probe_interval=600
gp_segment_connect_timeout=1800|1800
gp_interconnect_queue_depth=16
gp_interconnect_snd_queue_depth=16
gp_interconnect_min_retries_before_timeout=100
gp_interconnect_fc_method=loss_advance
autovacuum=off
max_connections=500|100
max_prepared_transactions=100
work_mem=512MB
vector.force_vectorization=off
vector.enable_vector_optimizer=off
vector.min_concatenate_rows=0
vector.max_batch_size=16384
vector.partition_top_k=100
vector.enable_vectorization={vec}
vector.enable_vec_pipeline={pipe}
statement_timeout={timeout_ms}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("w"); ap.add_argument("cluster"); ap.add_argument("set", choices=["h", "ds"])
    ap.add_argument("scale", type=int); ap.add_argument("mode", choices=["load", "run"])
    ap.add_argument("--tags", default=""); ap.add_argument("--upload", default="false")
    ap.add_argument("--vec", default="on"); ap.add_argument("--am", default="pax")
    ap.add_argument("--pipeline", choices=["off", "on"], default="off")
    ap.add_argument("--rounds", type=int, default=1)    # SINGLE_USER_ITERATIONS: each query N times back to back
    ap.add_argument("--streams", type=int, default=1)   # >1: proteus multi-user test, N concurrent query streams
    ap.add_argument("--random", default="false")   # proteus default: hash distribution (distkeys)
    ap.add_argument("--timeout-s", type=int, default=1800)
    ap.add_argument("--guc", action="append", default=[]); ap.add_argument("--pre-sql", default="")
    a = ap.parse_args()
    C = f"{a.w}/clusters/{a.cluster}"
    cj = json.load(open(f"{C}/cluster.json")); hj = json.load(open(f"{C}/host.json"))
    suffix = f"sf{a.scale}{a.am}" + ("rand" if a.random == "true" else "")   # hash -> sf10pax, random -> sf10paxrand
    pipe = a.pipeline if a.mode == "run" else "off"     # loads always without pipeline
    streams = a.streams if a.mode == "run" else 1
    name = (f"tpcbench_{a.cluster}_{a.set}_{suffix}_{a.mode}" + (f"_c{streams}" if streams > 1 else "")
            + ("_pipe" if pipe == "on" else ""))
    multi = streams > 1
    d = f"{a.w}/proteus/configs/{name}"; os.makedirs(d, exist_ok=True)
    load = a.mode == "load"
    tf = lambda b: "true" if b else "false"
    pre = a.pre_sql or f"set vector.enable_vectorization={a.vec}; set vector.enable_vec_pipeline={pipe};"
    conf = {
        "CHIP_TYPE": "arm" if hj["arch"] == "aarch64" else "x86",
        "ENABLE_GUC_CONFIGURATION": "true",
        "GEN_DATA_SCALE": str(a.scale), "MULTI_USER_COUNT": str(streams),
        "RUN_COMPILE_TPC": tf(load), "RUN_GEN_DATA": tf(load), "GEN_NEW_DATA": tf(load),
        "RUN_INIT": tf(load), "RUN_DDL": tf(load), "DROP_EXISTING_TABLES": tf(load), "RUN_LOAD": tf(load),
        "RUN_ANALYZE": "false",              # ANALYZE is done explicitly by load.sh, never inside a timed run
        "RUN_SQL": tf(not load and not multi), "RUN_QGEN": tf(not load and not multi), "UNIFY_QGEN_SEED": "true",
        "RUN_MULTI_USER_QGEN": tf(multi), "RNGSEED": "2016032410",   # fixed: every concurrent run gets the same streams
        "QUERY_INTERVAL": "0", "ON_ERROR_STOP": "0",
        "RUN_SINGLE_USER_REPORTS": tf(not load and not multi),   # step 06 writes overview.log (totals for the report DB)
        "RUN_MULTI_USER": tf(multi), "RUN_MULTI_USER_REPORTS": tf(multi),
        "RESET_ENV_ON_SEGMENT": "false", "RUN_SCORE": "false",
        "SINGLE_USER_ITERATIONS": str(a.rounds if not load else 1), "EXPLAIN_ANALYZE": "false", "RETURN_RESULTS": "true",
        "RANDOM_DISTRIBUTION": a.random, "STATEMENT_MEM": "6GB", "STATEMENT_MEM_MULTI_USER": "1GB",
        "GPFDIST_LOCATION": "p",
        "SMALL_STORAGE": "compresstype=zstd, compresslevel=5", "MEDIUM_STORAGE": "compresstype=zstd, compresslevel=5",
        "LARGE_STORAGE": "compresstype=zstd, compresslevel=5", "TABLE_SPACE": "pg_default",
        "REPORT_TYPE": "performance" if not load else "setup",   # 'setup' also prevents proteus' drop_caches path
        "OUTPUT_TO_REPORT_DB": a.upload if not load else "false", "SYS_METRICS": "false",
        "BENCH_ROLE_SUFFIX": f"bench_{suffix}", "SCHEMA_NAME_PREFIX": f"{suffix}_tpc", "TABLE_AM": a.am,
        "FEATURE_TAGS": a.tags, "PRE_QUERY_SQL": pre,
    }
    with open(f"{d}/test.conf", "w") as f:
        for k, v in conf.items():
            f.write(f'export {k}="{v}"\n')
        f.write('export GREENPLUM_PATH=$GPHOME/greenplum_path.sh\nexport ADMIN_USER="${USER}"\n'
                'export OSVERSION=$(uname)\nexport MASTER_HOST=$(hostname -s)\nexport LD_PRELOAD=/lib64/libz.so.1\n')
    gucs = GUC_BASE.format(vec=a.vec, pipe=pipe, timeout_ms=a.timeout_s * 1000)
    for g in a.guc:
        k = g.split("=", 1)[0]
        gucs = "\n".join(l for l in gucs.splitlines() if not l.startswith(k + "=")) + f"\n{g}\n"
    open(f"{d}/guc.conf", "w").write(gucs)
    hosts = cj["hosts"]
    disks = [x for x in hj["disks"] if x["mount"].startswith("/data")] or hj["disks"]
    env = {
        "PGHOST": cj["coord_host"], "PGDATABASE": "gpadmin", "PGPORT": str(cj["port"]), "PGUSER": "gpadmin",
        "CPU_CORES": str(hj["cores"]), "MEMORY_GB": str(hj["mem_gb"]),
        "DISK_CAPACITY_TB": str(round(sum(x["size_gb"] for x in disks) / 1024)),
        "OPERATING_SYSTEM": f"{hj['os']} ({hj.get('cpu_model', '')})".strip(),
        "DISK_COUNT": str(len(disks)), "SERVER_TYPE": "Physical Server",
        "NUMBER_OF_NODES": str(len(hosts)), "TOTAL_SEGMENTS": str(cj["segs_per_host"] * len(hosts)),
    }
    with open(f"{C}/proteus_env.conf", "w") as f:
        for k, v in env.items():
            f.write(f'export {k}="{v}"\n')
    print(name)


if __name__ == "__main__":
    main()
