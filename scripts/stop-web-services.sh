#!/usr/bin/env bash
set -euo pipefail

# Backward-compatible name. Never stop the independently managed model service.
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/stop-java-backend.sh" "$@"

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="${project_root}/.runtime"

stop_process() {
    local pid_file="$1"
    local expected="$2"
    [[ -f "${pid_file}" ]] || return 0
    local pid
    pid="$(<"${pid_file}")"
    if kill -0 "${pid}" 2>/dev/null; then
        if ps -p "${pid}" -o args= | grep -Fq "${expected}"; then
            kill "${pid}"
            for _ in $(seq 1 20); do
                kill -0 "${pid}" 2>/dev/null || break
                sleep 0.25
            done
        else
            echo "Refusing to stop PID ${pid}: command does not match ${expected}" >&2
            return 1
        fi
    fi
    rm -f "${pid_file}"
}

stop_process "${runtime_dir}/java-backend.pid" "pasa-java-backend"
stop_process "${runtime_dir}/python-model.pid" "uvicorn backend.main:app"
echo "Web stack stopped"
