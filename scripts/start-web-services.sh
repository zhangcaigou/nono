#!/usr/bin/env bash
set -euo pipefail

# Backward-compatible name. Model-service lifecycle belongs to the model team;
# this repository-side command now starts only the Java business backend.
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/start-java-backend.sh" "$@"

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="${project_root}/.runtime"
env_file="${PASA_ENV_FILE:-${project_root}/.env}"
python_bin="${PASA_PYTHON_BIN:-/home/qpd/miniconda3/envs/uav_avl/bin/python}"
java_bin="${PASA_JAVA_BIN:-/home/qpd/miniconda3/envs/pasa_java/bin/java}"
java_jar="${PASA_JAVA_JAR:-${project_root}/java-backend/target/pasa-java-backend-0.1.0-SNAPSHOT.jar}"
service_tmp_dir="${PASA_TMPDIR:-${runtime_dir}/tmp}"

mkdir -p "${runtime_dir}" "${service_tmp_dir}"
if [[ -f "${env_file}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${env_file}"
    set +a
fi

: "${PASA_INTERNAL_TOKEN:?Set PASA_INTERNAL_TOKEN in ${env_file}}"
PASA_ENGINE_MODE="${PASA_ENGINE_MODE:-production}"
if [[ "${PASA_ENGINE_MODE}" == "production" ]]; then
    : "${SERPER_API_KEY:?Set SERPER_API_KEY in ${env_file} for production mode}"
    : "${OPENALEX_API_KEY:?Set OPENALEX_API_KEY in ${env_file} for production mode}"
fi

if [[ -f "${runtime_dir}/python-model.pid" ]] && kill -0 "$(<"${runtime_dir}/python-model.pid")" 2>/dev/null; then
    echo "Python model service is already running"
    exit 1
fi
if [[ -f "${runtime_dir}/java-backend.pid" ]] && kill -0 "$(<"${runtime_dir}/java-backend.pid")" 2>/dev/null; then
    echo "Java backend is already running"
    exit 1
fi

cd "${project_root}"
setsid env \
    TMPDIR="${service_tmp_dir}" \
    PASA_ENGINE_MODE="${PASA_ENGINE_MODE}" \
    PASA_INTERNAL_TOKEN="${PASA_INTERNAL_TOKEN}" \
    PASA_CRAWLER_DEVICE="${PASA_CRAWLER_DEVICE:-cuda:0}" \
    PASA_SELECTOR_DEVICE="${PASA_SELECTOR_DEVICE:-cuda:1}" \
    PASA_MAX_WORKERS="${PASA_MAX_WORKERS:-1}" \
    PASA_THREADS_NUM="${PASA_THREADS_NUM:-20}" \
    SERPER_API_KEY="${SERPER_API_KEY:-}" \
    OPENALEX_API_KEY="${OPENALEX_API_KEY:-}" \
    "${python_bin}" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 \
    </dev/null >"${runtime_dir}/python-model.log" 2>&1 &
python_pid=$!
printf '%s\n' "${python_pid}" >"${runtime_dir}/python-model.pid"

cleanup_on_error() {
    kill "${python_pid}" 2>/dev/null || true
}
trap cleanup_on_error ERR

for _ in $(seq 1 30); do
    if curl --noproxy '*' -fsS \
        -H "X-Internal-Token: ${PASA_INTERNAL_TOKEN}" \
        http://127.0.0.1:8000/internal/v1/health 2>/dev/null \
        | "${python_bin}" -c 'import json,sys; raise SystemExit(not json.load(sys.stdin).get("ready", False))' 2>/dev/null; then
        break
    fi
    sleep 1
done
kill -0 "${python_pid}" 2>/dev/null

setsid env \
    TMPDIR="${service_tmp_dir}" \
    SERVER_ADDRESS="${SERVER_ADDRESS:-0.0.0.0}" \
    SERVER_PORT="${SERVER_PORT:-8080}" \
    PASA_MODEL_SERVICE_BASE_URL="http://127.0.0.1:8000" \
    PASA_INTERNAL_TOKEN="${PASA_INTERNAL_TOKEN}" \
    PASA_MODEL_READ_TIMEOUT="${PASA_MODEL_READ_TIMEOUT:-PT30M}" \
    PASA_TASK_WORKERS="${PASA_TASK_WORKERS:-1}" \
    PASA_CORS_ORIGINS="${PASA_CORS_ORIGINS:-http://localhost:3000,http://localhost:5173}" \
    "${java_bin}" -Djava.io.tmpdir="${service_tmp_dir}" -jar "${java_jar}" \
    </dev/null >"${runtime_dir}/java-backend.log" 2>&1 &
java_pid=$!
printf '%s\n' "${java_pid}" >"${runtime_dir}/java-backend.pid"

for _ in $(seq 1 30); do
    if curl --noproxy '*' -fsS "http://127.0.0.1:${SERVER_PORT:-8080}/api/v1/health" 2>/dev/null \
        | "${python_bin}" -c 'import json,sys; raise SystemExit(not json.load(sys.stdin).get("ready", False))' 2>/dev/null; then
        trap - ERR
        echo "Web stack started: engine=${PASA_ENGINE_MODE}, Java port=${SERVER_PORT:-8080}"
        exit 0
    fi
    sleep 1
done

kill "${java_pid}" "${python_pid}" 2>/dev/null || true
echo "Web stack failed to become healthy; inspect ${runtime_dir}/*.log" >&2
exit 1
