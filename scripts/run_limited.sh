#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 COMMAND [ARG ...]" >&2
  exit 2
fi

for bin in taskset prlimit awk; do
  command -v "$bin" >/dev/null || { echo "required command not found: $bin" >&2; exit 127; }
done

allowed=$(taskset -pc "$$" | sed 's/.*: //')
cpu_set=$(awk -v list="$allowed" 'BEGIN {
  n=split(list, groups, ","); count=0; out=""
  for (i=1; i<=n && count<2; i++) {
    m=split(groups[i], bounds, "-"); start=bounds[1]; end=(m==2 ? bounds[2] : bounds[1])
    for (cpu=start; cpu<=end && count<2; cpu++) {
      if (out!="") out=out ","
      out=out cpu; count++
    }
  }
  print out
}')

if [[ -z "$cpu_set" ]]; then
  echo "could not determine an allowed CPU set" >&2
  exit 1
fi

# CPU affinity restricts execution to two logical CPUs; prlimit caps virtual
# address space, not resident memory. cgroup RAM enforcement is unavailable here.
exec taskset -c "$cpu_set" prlimit --as=2147483648 -- "$@"
