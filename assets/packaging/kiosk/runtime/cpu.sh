#!/bin/sh
set -eu
governor=$(cat /etc/carvera/cpu-governor)
case "$governor" in performance|schedutil) ;; *) exit 1 ;; esac
for policy in /sys/devices/system/cpu/cpufreq/policy*; do
    [ -e "$policy/scaling_governor" ] || continue
    printf '%s' "$governor" > "$policy/scaling_governor"
done
