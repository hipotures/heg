PYTHON ?= python3
PYTHONPATH := src
WORKSPACE ?= ./workspace
PORT ?= 8080

CXX ?= c++
CXXFLAGS ?= -O3 -std=c++17 -Wall -Wextra -Wpedantic
CYCLECHECK := _build/sglab-cyclecheck

.PHONY: doctor test check init serve dashboard-smoke benchmark-smoke cyclecheck clean

doctor:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m sglab doctor

test: cyclecheck
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests -v

check: cyclecheck
	$(PYTHON) -m compileall -q src tests

cyclecheck: $(CYCLECHECK)

$(CYCLECHECK): cpp/sglab_cyclecheck.cpp
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
