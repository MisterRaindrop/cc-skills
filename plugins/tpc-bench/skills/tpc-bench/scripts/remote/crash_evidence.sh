#!/bin/bash
# crash_evidence.sh <workdir> <cluster> <since_epoch> -- read-only evidence after a cluster went down during a run
W=$1; NAME=$2; SINCE=$3
set +u; source $W/clusters/$NAME/cluster.env; set -u
echo "== segments not up"; psql -Atc "select content,role,status,hostname,port,datadir from gp_segment_configuration where status<>'u'" 2>&1
echo "== kernel log (OOM killer etc.) since $(date -d @$SINCE '+%F %T')"
sudo -n dmesg -T 2>/dev/null | awk -v s="$(date -d @$SINCE '+%a %b %e %H:%M')" 'f||index($0,s){f=1} f' | grep -iE "oom|killed process|segfault|out of memory" | tail -40
echo "== core files newer than the run start"
for d in $(psql -Atc "select datadir from gp_segment_configuration" 2>/dev/null) $COORDINATOR_DATA_DIRECTORY; do
  find $d -maxdepth 1 -name 'core*' -newermt "@$SINCE" 2>/dev/null
done
find /var/crash /var/lib/systemd/coredump -newermt "@$SINCE" 2>/dev/null | head
echo "== PANIC/FATAL in segment logs since run start"
for d in $(psql -Atc "select datadir from gp_segment_configuration" 2>/dev/null); do
  find $d/log -name '*.csv' -newermt "@$SINCE" 2>/dev/null | xargs -r grep -hE ',"(PANIC|FATAL)",' 2>/dev/null | cut -c1-300 | tail -5
done
