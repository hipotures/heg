PYTHON ?= python3
PYTHONPATH := src
WORKSPACE ?= ./workspace
PORT ?= 8080

CXX ?= c++
CXXFLAGS ?= -O3 -std=c++17 -Wall -Wextra -Wpedantic
CYCLECHECK := _build/sglab-cyclecheck
SCORE_WORKER := _build/sglab-score-worker
RUST_ENGINE := _build/sglab-rust-engine

.PHONY: doctor test check init serve dashboard-smoke benchmark-smoke cyclecheck score-worker rust-engine clean

doctor:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m sglab doctor

test: cyclecheck score-worker
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests -v

check: cyclecheck score-worker
	$(PYTHON) -m compileall -q src tests

cyclecheck: $(CYCLECHECK)

$(CYCLECHECK): cpp/sglab_cyclecheck.cpp
	mkdir -p _build
	$(CXX) $(CXXFLAGS) $< -o $@

score-worker: $(SCORE_WORKER)

$(SCORE_WORKER): cpp/sglab_score_worker.cpp
	mkdir -p _build
	$(CXX) $(CXXFLAGS) $< -o $@

rust-engine: $(RUST_ENGINE)

$(RUST_ENGINE): rust/sglab-engine/Cargo.toml rust/sglab-engine/src/*.rs
	mkdir -p _build
	RUSTFLAGS="-C target-cpu=native" cargo build --release --manifest-path rust/sglab-engine/Cargo.toml
	cp rust/sglab-engine/target/release/sglab-rust-engine $@

init:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m sglab init --workspace $(WORKSPACE)

serve: init
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m sglab serve --workspace $(WORKSPACE) --port $(PORT)

dashboard-smoke:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m sglab dashboard-smoke

benchmark-smoke:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m sglab benchmark-smoke

clean:
	rm -rf .coverage .pytest_cache workspace build dist *.egg-info _build
