PYTHON ?= python3
PYTHONPATH := src
WORKSPACE ?= ./workspace
PORT ?= 8080

.PHONY: doctor test check init serve dashboard-smoke benchmark-smoke clean

doctor:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m sglab doctor

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests -v

check:
	$(PYTHON) -m compileall -q src tests

init:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m sglab init --workspace $(WORKSPACE)

serve: init
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m sglab serve --workspace $(WORKSPACE) --port $(PORT)

dashboard-smoke:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m sglab dashboard-smoke

benchmark-smoke:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m sglab benchmark-smoke

clean:
	rm -rf .coverage .pytest_cache workspace build dist *.egg-info
