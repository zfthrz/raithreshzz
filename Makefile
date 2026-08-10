PYTHON ?= python

.PHONY: check test smoke history-init history-example history-validate compile

check:
	$(PYTHON) scripts/check_project.py

test:
	pytest -q

smoke:
	$(PYTHON) scripts/smoke_portable.py

history-init:
	$(PYTHON) session_history.py init

history-example:
	$(PYTHON) session_history.py import examples/monza_analyze_v3_8.json

history-validate:
	$(PYTHON) validate_history_db.py

compile:
	$(PYTHON) -m compileall -q .
