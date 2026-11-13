#!/bin/bash
# layout.sh -- libarrow load address mod 256MB for every postmaster of this cluster, on every host (needs cluster.env;
# run on the coordinator; other hosts via ssh).
# On Kunpeng-920 a 256MB boundary between libarrow's PLT and Numeric128 kernels (base mod 256MB in F6..FC MB)
# makes some scans ~30% slower (branch mispredict). Recorded so such runs can be recognised as noise.
n=0; bad=0; me=$(hostname -s)
# prints "<pid|-> <libarrow base|-> <arch>" for one data dir
probe='p=$(head -1 DD/postmaster.pid 2>/dev/null); b=; [ -n "$p" ] && b=$(grep -m1 libarrow.so /proc/$p/maps 2>/dev/null | cut -d- -f1); echo "${p:--} ${b:--} $(uname -m)"'
while IFS='|' read -r h dd; do
  [ -z "$dd" ] && continue
  cmd=${probe//DD/$dd}
  # ssh -n: otherwise ssh eats the rest of the while-read input and the loop stops after the first remote host
  if [ "$h" = "$me" ]; then out=$(bash -c "$cmd"); else out=$(ssh -n -o BatchMode=yes $h "$cmd" 2>/dev/null); fi
  read -r p b arch <<< "$out"
  [ "${p:--}" = - ] && { echo "$h:$dd no postmaster.pid"; continue; }
  [ "${b:--}" = - ] && { echo "$h:$dd pid=$p libarrow not mapped"; continue; }
  n=$((n+1)); r=$(( (0x$b >> 20) & 0xff )); flag=ok
  if [ "$arch" = aarch64 ] && [ $r -ge $((0xf6)) ] && [ $r -le $((0xfc)) ]; then flag=BAD; bad=$((bad+1)); fi
  printf "%s:%s pid=%s base=%s mod256MB=%02XMB %s\n" $h $dd $p $b $r $flag
done < <(psql -Atc "select hostname, datadir from gp_segment_configuration where role='p' order by content")
echo "postmasters=$n bad=$bad"
