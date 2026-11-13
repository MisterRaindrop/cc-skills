#!/bin/bash
# fetch_deploy.sh <workdir> <pipeline> <rpm_url> <release_yaml_url>   (root on each host)
# Downloads the CI RPM into <workdir>/pkgs/<pipeline>/ (kept as archive) and unpacks it into
# <workdir>/gphome-<pipeline>/ with rpm2cpio. Never runs `rpm -i`, never touches /usr/local links or the rpm db.
# Idempotent: skips download / unpack when already done and verified.
set -euo pipefail
W=$1; ID=$2; RPM_URL=$3; YAML_URL=${4:-}
P=$W/pkgs/$ID; G=$W/gphome-$ID; mkdir -p $P
log(){ echo "[$(date '+%F %T')] fetch_deploy: $*"; }
RPM=$P/$(basename "$RPM_URL")
want=$(curl -sfI -m 30 "$RPM_URL" | awk 'tolower($1)=="content-length:"{print $2}' | tr -d '\r')
[ -n "$want" ] || { log "ERROR cannot HEAD $RPM_URL"; exit 2; }
if [ -f "$RPM" ] && [ "$(stat -c %s "$RPM")" = "$want" ]; then
  log "package already downloaded ($want bytes)"
else
  log "downloading $RPM_URL ($want bytes)"
  curl -sf -m 3600 -o "$RPM.part" "$RPM_URL"; mv "$RPM.part" "$RPM"
fi
[ "$(stat -c %s "$RPM")" = "$want" ] || { log "ERROR size mismatch"; exit 3; }
rpm -K --nosignature "$RPM" | tee $P/rpm_check.txt | grep -qi "digests.*OK\|md5.*OK\|sha256.*OK" || { log "ERROR rpm digest check failed"; exit 4; }
[ -n "$YAML_URL" ] && curl -sf -m 60 -o $P/release-info.yaml "$YAML_URL" || true
rpm -qpi "$RPM" > $P/rpm_info.txt 2>/dev/null || true

if [ -x "$G/bin/postgres" ] && [ -f "$G/.tpcbench_ok" ]; then
  log "already unpacked: $G"
else
  T=$W/.unpack-$ID; rm -rf $T $G; mkdir -p $T
  log "unpacking into $G"
  ( cd $T && rpm2cpio "$RPM" | cpio -idm --quiet )
  src=$(ls -d $T/usr/local/hashdata-lightning-* | head -1)
  [ -d "$src" ] || { log "ERROR unexpected rpm layout: $(ls -R $T | head)"; exit 5; }
  mv "$src" "$G"; rm -rf $T
  chown -R gpadmin:gpadmin "$G"
fi
# Multi-host fix (applied to our own copy only, idempotent): GP starts segments remotely with
#   ssh host ". <gphome>/cloudberry-env.sh; <gphome>/sbin/gpsegstart.py ..."
# and gpsegstart checks the version with `bash -c '$GPHOME/bin/postgres --gp-version'`. RHEL's bash re-reads
# ~/.bashrc in any non-interactive shell that sees SSH_CLIENT with SHLVL<2 (SSH_SOURCE_BASHRC); a gpadmin ~/.bashrc
# that sources another install's greenplum_path.sh then switches GPHOME back -> "Local Software Version does not match".
# We never edit ~/.bashrc: drop the ssh marker in our env script so its subshells keep this GPHOME.
if ! grep -q tpcbench-ssh-bashrc-fix $G/cloudberry-env.sh; then
  printf '\n# tpcbench-ssh-bashrc-fix: keep GPHOME in subshells of ssh sessions (see tpc-bench fetch_deploy.sh)\nunset SSH_CLIENT SSH2_CLIENT\n' >> $G/cloudberry-env.sh
fi
# sanity: binaries start, no missing libraries
ver=$(su - gpadmin -c "source $G/greenplum_path.sh && postgres --gp-version" 2>&1)
missing=$(su - gpadmin -c "source $G/greenplum_path.sh && ldd $G/bin/postgres $G/lib/postgresql/vectorization.so 2>/dev/null; ldd \$(ls $G/lib/libarrow*.so* 2>/dev/null | head -1) 2>/dev/null" | grep "not found" | sort -u || true)
echo "$ver" > $P/gp_version.txt
if [ -n "$missing" ]; then log "ERROR missing libraries:"; echo "$missing"; exit 6; fi
touch $G/.tpcbench_ok
log "OK $ver"
