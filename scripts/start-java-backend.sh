#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="${project_root}/.runtime"
env_file="${PASA_ENV_FILE:-${project_root}/.env}"
java_bin="${PASA_JAVA_BIN:-/home/qpd/miniconda3/envs/pasa_java/bin/java}"
build_user="$(id -un)"
java_jar="${PASA_JAVA_JAR:-${project_root}/java-backend/target-${build_user}/pasa-java-backend-0.1.0-SNAPSHOT.jar}"
service_tmp_dir="${PASA_TMPDIR:-${TMPDIR:-/tmp}/pasa-java-${UID}}"

mkdir -p "${runtime_dir}" "${service_tmp_dir}"
if [[ -f "${env_file}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${env_file}"
    set +a
fi

: "${PASA_INTERNAL_TOKEN:?Set PASA_INTERNAL_TOKEN in ${env_file}}"
[[ -x "${java_bin}" ]] || { echo "Java executable not found: ${java_bin}" >&2; exit 1; }
[[ -f "${java_jar}" ]] || { echo "Java backend jar not found: ${java_jar}" >&2; exit 1; }

pid_file="${runtime_dir}/java-backend.pid"
if [[ -f "${pid_file}" ]]; then
    existing_pid="$(<"${pid_file}")"
    if ps -p "${existing_pid}" -o args= 2>/dev/null | grep -Fq "${java_jar}"; then
        echo "Java backend is already running with PID ${existing_pid}"
        exit 0
    fi
    rm -f "${pid_file}"
fi

model_health="$(curl --noproxy '*' -fsS http://127.0.0.1:8000/internal/v1/health 2>/dev/null || true)"
if [[ "${model_health}" != *'"ready":true'* && "${model_health}" != *'"ready": true'* ]]; then
    echo "Warning: model service is not currently ready; Java will start in degraded mode" >&2
fi

cd "${project_root}"
setsid env \
    TMPDIR="${service_tmp_dir}" \
    SERVER_ADDRESS="${SERVER_ADDRESS:-0.0.0.0}" \
    SERVER_PORT="${SERVER_PORT:-8080}" \
    PASA_MODEL_SERVICE_BASE_URL="${PASA_MODEL_SERVICE_BASE_URL:-http://127.0.0.1:8000}" \
    PASA_INTERNAL_TOKEN="${PASA_INTERNAL_TOKEN}" \
    PASA_MODEL_READ_TIMEOUT="${PASA_MODEL_READ_TIMEOUT:-PT30M}" \
    PASA_TASK_WORKERS="${PASA_TASK_WORKERS:-1}" \
    PASA_CORS_ORIGINS="${PASA_CORS_ORIGINS:-http://localhost:3000,http://localhost:5173}" \
    "${java_bin}" -Djava.io.tmpdir="${service_tmp_dir}" -jar "${java_jar}" \
    </dev/null >"${runtime_dir}/java-backend.log" 2>&1 &
java_pid=$!
printf '%s\n' "${java_pid}" >"${pid_file}"

for _ in $(seq 1 30); do
    if health="$(curl --noproxy '*' -fsS "http://127.0.0.1:${SERVER_PORT:-8080}/api/v1/health" 2>/dev/null)"; then
        echo "Java backend started with PID ${java_pid}"
        echo "${health}"
        exit 0
    fi
    if ! ps -p "${java_pid}" >/dev/null 2>&1; then
        echo "Java backend exited during startup; inspect ${runtime_dir}/java-backend.log" >&2
        rm -f "${pid_file}"
        exit 1
    fi
    sleep 1
done

kill "${java_pid}" 2>/dev/null || true
rm -f "${pid_file}"
echo "Java backend failed to become reachable; inspect ${runtime_dir}/java-backend.log" >&2
exit 1
