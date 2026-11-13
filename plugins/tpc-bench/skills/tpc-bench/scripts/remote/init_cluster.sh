#!/bin/bash
# init_cluster.sh <workdir> <name> <build_id> <coord_port> <segs_per_host> <hosts_csv> <datadirs_csv>   (gpadmin, on the coordinator host)
# Creates a new mirrorless cluster owned by tpc-bench:
#   coordinator  <workdir>/clusters/<name>/coord/gpseg-1  on the first host
#   primaries    <datadir_i>/tpcbench_<name>/primary/gpsegN  (datadirs used round-robin, same list on every host)
#   ports        coordinator <coord_port>, primaries from <coord_port>+1
# Writes <workdir>/clusters/<name>/{cluster.env,cluster.json,gpinitsystem_config,hostfile} and marker files
# (.tpcbench_cluster) so discovery recognises it. Refuses if any port is taken or any target dir exists.
set -euo pipefail
W=$1; NAME=$2; ID=$3; CPORT=$4; NSEG=$5; HOSTS=$6; DIRS=$7
C=$W/clusters/$NAME; G=$W/gphome-$ID
log(){ echo "[$(date '+%F %T')] init_cluster: $*"; }
[ -f $G/.tpcbench_ok ] || { log "ERROR build $ID not deployed at $G"; exit 2; }
[ -e $C/cluster.json ] && { log "ERROR cluster $NAME already exists ($C)"; exit 3; }
IFS=, read -ra HL <<< "$HOSTS"; IFS=, read -ra DL <<< "$DIRS"
COORD=${HL[0]}
# ports: coordinator + NSEG consecutive primaries must be free on every host
for h in "${HL[@]}"; do
  used=$(ssh -o BatchMode=yes $h "ss -ltnH | awk '{print \$4}' | grep -oE '[0-9]+\$' | sort -u")
  for p in $(seq $CPORT $((CPORT + NSEG))); do
    echo "$used" | grep -qx $p && { log "ERROR port $p in use on $h"; exit 4; }
  done
  for d in "${DL[@]}"; do
    ssh -o BatchMode=yes $h "test -e $d/tpcbench_$NAME" && { log "ERROR $h:$d/tpcbench_$NAME exists"; exit 5; }
  done
done
mkdir -p $C/coord
printf "%s\n" "${HL[@]}" > $C/hostfile
dd=""
for i in $(seq 0 $((NSEG - 1))); do dd="$dd ${DL[$((i % ${#DL[@]}))]}/tpcbench_$NAME/primary"; done
for h in "${HL[@]}"; do
  ssh -o BatchMode=yes $h "mkdir -p $(for d in "${DL[@]}"; do printf '%s ' $d/tpcbench_$NAME/primary; done) && for d in ${DL[*]}; do touch \$d/tpcbench_$NAME/.tpcbench_cluster; done"
done
cat > $C/gpinitsystem_config <<EOF
ARRAY_NAME="tpcbench_$NAME"
SEG_PREFIX=gpseg
PORT_BASE=$((CPORT + 1))
declare -a DATA_DIRECTORY=($dd)
COORDINATOR_HOSTNAME=$COORD
COORDINATOR_DIRECTORY=$C/coord
COORDINATOR_PORT=$CPORT
TRUSTED_SHELL=ssh
ENCODING=UNICODE
DATABASE_NAME=gpadmin
MACHINE_LIST_FILE=$C/hostfile
EOF
cat > $C/cluster.env <<EOF
# tpc-bench cluster $NAME -- source this (gpadmin). Build switch = edit TPCBENCH_BUILD + restart (cluster.sh use <id>).
export TPCBENCH_W=$W TPCBENCH_CLUSTER=$NAME
export TPCBENCH_BUILD=\$(cat $C/build.cur)
source $W/gphome-\$TPCBENCH_BUILD/greenplum_path.sh
export LD_PRELOAD=/lib64/libz.so.1
export COORDINATOR_DATA_DIRECTORY=$C/coord/gpseg-1
export PGPORT=$CPORT PGDATABASE=gpadmin PGHOST=$COORD PGUSER=gpadmin
unset https_proxy http_proxy HTTPS_PROXY HTTP_PROXY
export TERM=xterm   # proteus calls tput sc/rc under set -e; ssh+su gives TERM=dumb (no sc capability -> silent exit 1)
export PYTHONPATH=$W/pylib:\${PYTHONPATH:-}
EOF
echo $ID > $C/build.cur
set +u; source $C/cluster.env; set -u
log "gpinitsystem: $NAME build $ID coord $COORD:$CPORT, $NSEG primaries/host on ${HL[*]}"
set +e
gpinitsystem -a -c $C/gpinitsystem_config > $C/gpinitsystem.out 2>&1
rc=$?
set -e
tail -5 $C/gpinitsystem.out
# gpinitsystem returns 1 on warnings; judge by whether the cluster answers
if ! psql -d gpadmin -Atc "select count(*) from gp_segment_configuration where status='u'" > $C/up.txt 2>&1; then
  log "ERROR gpinitsystem rc=$rc, cluster not answering (see $C/gpinitsystem.out)"; exit 6
fi
touch $C/coord/.tpcbench_cluster
python3 - "$C" "$NAME" "$ID" "$CPORT" "$NSEG" "$HOSTS" "$DIRS" <<'PY'
import json, sys
c, name, bid, port, nseg, hosts, dirs = sys.argv[1:]
json.dump(dict(name=name, build=int(bid) if bid.isdigit() else bid, coord_host=hosts.split(",")[0], port=int(port),
               segs_per_host=int(nseg), hosts=hosts.split(","), datadirs=dirs.split(","),
               coord_dir=f"{c}/coord/gpseg-1"), open(f"{c}/cluster.json", "w"), indent=1)
PY
log "OK segments up: $(cat $C/up.txt)"
