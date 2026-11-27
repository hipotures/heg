#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOLVER_DIR="${ROOT}/_build/solvers"
mkdir -p "${SOLVER_DIR}"

# 1. Build CaDiCaL (rel-2.1.3)
if [ ! -x "${SOLVER_DIR}/cadical" ]; then
    echo "=== Building CaDiCaL rel-2.1.3 ==="
    if [ ! -d "${SOLVER_DIR}/cadical-src" ]; then
        git clone --depth 1 --branch rel-2.1.3 https://github.com/arminbiere/cadical.git "${SOLVER_DIR}/cadical-src"
    fi
    (
        cd "${SOLVER_DIR}/cadical-src"
        ./configure
        make -j"$(nproc)"
    )
    cp "${SOLVER_DIR}/cadical-src/build/cadical" "${SOLVER_DIR}/cadical"
fi

# 2. Build drat-trim (master)
if [ ! -x "${SOLVER_DIR}/drat-trim" ]; then
    echo "=== Building drat-trim ==="
    if [ ! -d "${SOLVER_DIR}/drat-trim-src" ]; then
        git clone --depth 1 https://github.com/marijnheule/drat-trim.git "${SOLVER_DIR}/drat-trim-src"
    fi
    (
        cd "${SOLVER_DIR}/drat-trim-src"
        gcc -O3 -std=gnu99 drat-trim.c -o drat-trim
    )
    cp "${SOLVER_DIR}/drat-trim-src/drat-trim" "${SOLVER_DIR}/drat-trim"
fi

# 3. Build repo check_drat.cpp & sglab_cyclecheck_large.cpp
g++ -O3 -std=c++17 "${ROOT}/tools/extremal/check_drat.cpp" -o "${SOLVER_DIR}/check-drat"
g++ -O3 -std=c++17 "${ROOT}/tools/extremal/sglab_cyclecheck_large.cpp" -o "${SOLVER_DIR}/sglab-cyclecheck-large"

# 4. Self-test on PHP(3,2) UNSAT -> DRAT -> drat-trim + check-drat
TMP_CNF="${SOLVER_DIR}/selftest_php32.cnf"
TMP_DRAT="${SOLVER_DIR}/selftest_php32.drat"
cat > "${TMP_CNF}" <<'EOF'
p cnf 6 9
1 2 0
3 4 0
5 6 0
-1 -3 0
-1 -5 0
-3 -5 0
-2 -4 0
-2 -6 0
-4 -6 0
EOF

set +e
"${SOLVER_DIR}/cadical" --no-binary "${TMP_CNF}" "${TMP_DRAT}" > /dev/null 2>&1
RC=$?
set -e
if [ "${RC}" -ne 20 ]; then
    echo "ERROR: CaDiCaL selftest expected exit 20 (UNSAT), got ${RC}" >&2
    exit 1
fi

"${SOLVER_DIR}/drat-trim" "${TMP_CNF}" "${TMP_DRAT}"
"${SOLVER_DIR}/check-drat" "${TMP_CNF}" "${TMP_DRAT}"
echo "=== Solvers built and verified ==="
"${SOLVER_DIR}/cadical" --version
