#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pid_file="${project_root}/.runtime/java-backend.pid"

if [[ ! -f "${pid_file}" ]]; then
    echo "Java backend PID file does not exist; nothing to stop"
    exit 0
fi

java_pid="$(<"${pid_file}")"
command_line="$(ps -p "${java_pid}" -o args= 2>/dev/null || true)"
if [[ -z "${command_line}" ]]; then
    rm -f "${pid_file}"
    echo "Removed stale Java backend PID file"
    exit 0
fi
if [[ "${command_line}" != *pasa-java-backend*.jar* ]]; then
    echo "Refusing to stop PID ${java_pid}: it is not the PaSa Java backend" >&2
    exit 1
fi

kill "${java_pid}"
for _ in $(seq 1 40); do
    ps -p "${java_pid}" >/dev/null 2>&1 || break
    sleep 0.25
done
if ps -p "${java_pid}" >/dev/null 2>&1; then
    echo "Java backend PID ${java_pid} did not stop" >&2
    exit 1
fi
rm -f "${pid_file}"
echo "Java backend stopped"
