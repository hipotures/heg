PYTHON ?= python3
PYTHONPATH := src
WORKSPACE ?= ./workspace
PORT ?= 8080

CXX ?= c++
CXXFLAGS ?= -O3 -std=c++17 -Wall -Wextra -Wpedantic
CYCLECHECK := _build/sglab-cyclecheck
SCORE_WORKER := _build/sglab-score-worker

.PHONY: doctor test check init serve dashboard-smoke benchmark-smoke cyclecheck score-worker clean

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
