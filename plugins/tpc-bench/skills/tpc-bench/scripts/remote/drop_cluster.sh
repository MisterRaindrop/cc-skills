#!/bin/bash
# drop_cluster.sh <workdir> <name>   (gpadmin, coordinator host) -- delete a tpc-bench cluster generation.
# Only with explicit user approval. Refuses unless every data dir carries the .tpcbench_cluster marker and the
# cluster is not the active generation of any logical name (<workdir>/clusters/*.active).
# Removes: the cluster's segment dirs <datadir>/tpcbench_<name> on every host, <workdir>/clusters/<name>, its .prev pointer.
# Runs (results) are kept: they are moved to <workdir>/clusters/_dropped/<name>/runs.
set -euo pipefail
W=$1; NAME=$2; C=$W/clusters/$NAME
log(){ echo "[$(date '+%F %T')] drop_cluster $NAME: $*"; }
for f in $W/clusters/*.active; do
  [ -f "$f" ] && [ "$(cat $f)" = "$NAME" ] && { log "ERROR $NAME is active ($f)"; exit 3; }
done
if [ -f $C/cluster.json ]; then
  read -r HOSTS DIRS < <(python3 -c "import json;c=json.load(open('$C/cluster.json'));print(','.join(c['hosts']),','.join(c['datadirs']))")
elif [ -f $C/hostfile ] && [ -f $C/gpinitsystem_config ]; then   # init that failed before writing cluster.json
  HOSTS=$(paste -sd, $C/hostfile)
  DIRS=$(grep -oE "[^ (]+/tpcbench_$NAME/primary" $C/gpinitsystem_config | sed "s#/tpcbench_$NAME/primary##" | sort -u | paste -sd,)
else
  log "ERROR no cluster $NAME"; exit 2
fi
IFS=, read -ra HL <<< "$HOSTS"; IFS=, read -ra DL <<< "$DIRS"
for h in "${HL[@]}"; do for d in "${DL[@]}"; do
  ssh -o BatchMode=yes $h "test -f $d/tpcbench_$NAME/.tpcbench_cluster" || { log "ERROR $h:$d/tpcbench_$NAME has no marker"; exit 4; }
done; done
$W/bin/cluster.sh $W $NAME stop || true
for h in "${HL[@]}"; do for d in "${DL[@]}"; do
  log "rm -rf $h:$d/tpcbench_$NAME"; ssh -o BatchMode=yes $h "rm -rf $d/tpcbench_$NAME"
done; done
mkdir -p $W/clusters/_dropped/$NAME
[ -d $C/runs ] && mv $C/runs $W/clusters/_dropped/$NAME/ || true
rm -rf $C $W/clusters/$NAME.prev
log "dropped (runs kept in $W/clusters/_dropped/$NAME)"
