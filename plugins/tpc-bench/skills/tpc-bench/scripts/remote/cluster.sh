#!/bin/bash
# cluster.sh <workdir> <name> status|start|stop|restart|use <build_id>   (gpadmin on the coordinator host)
# Only ever acts on the tpc-bench cluster <name> (its own COORDINATOR_DATA_DIRECTORY / port).
set -euo pipefail
W=$1; NAME=$2; CMD=$3; C=$W/clusters/$NAME
[ -f $C/cluster.env ] || { echo "no cluster $NAME under $W"; exit 2; }
set +u; source $C/cluster.env; set -u
log(){ echo "[$(date '+%F %T')] cluster $NAME: $*"; }
up(){ psql -d gpadmin -Atc "select count(*)||'/'||(select count(*) from gp_segment_configuration) from gp_segment_configuration where status='u'" 2>/dev/null; }
case $CMD in
  status) echo "build=$TPCBENCH_BUILD port=$PGPORT up=$(up || echo DOWN)"; postgres --gp-version ;;
  start) gpstart -a > $C/gpstart.out 2>&1 || true; log "up=$(up || echo DOWN)" ;;
  stop) gpstop -a -M fast > $C/gpstop.out 2>&1 || true; log "stopped" ;;
  restart) gpstop -a -M fast > $C/gpstop.out 2>&1 || true; gpstart -a > $C/gpstart.out 2>&1 || true; log "up=$(up || echo DOWN)" ;;
  use)
    ID=$4; [ -f $W/gphome-$ID/.tpcbench_ok ] || { log "ERROR build $ID not deployed"; exit 3; }
    if [ "$ID" = "$TPCBENCH_BUILD" ]; then log "already on $ID"; exit 0; fi
    old=$TPCBENCH_BUILD
    gpstop -a -M fast > $C/gpstop.out 2>&1 || true
    echo $ID > $C/build.cur
    set +u; source $C/cluster.env; set -u
    if ! gpstart -a > $C/gpstart.out 2>&1 || ! up >/dev/null; then
      log "ERROR start on $ID failed (catalog incompatible?), reverting to $old"; tail -5 $C/gpstart.out
      gpstop -a -M fast >/dev/null 2>&1 || true; echo $old > $C/build.cur
      set +u; source $C/cluster.env; set -u; gpstart -a >/dev/null 2>&1 || true; exit 4
    fi
    log "switched $old -> $ID up=$(up)" ;;
  *) echo "unknown command $CMD"; exit 1 ;;
esac
