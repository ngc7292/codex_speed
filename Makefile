PYTHON ?= python3
COMPOSE_FILE := deploy/prometheus/docker-compose.yml
COMPOSE := docker compose -f $(COMPOSE_FILE)

.PHONY: help install-dev test smoke compose-config deploy verify logs stop rollback notify-test install-shim uninstall-shim

help:
	@printf '%s\n' \
		'codex-speed targets:' \
		'  make install-dev     Install the Python package in editable mode' \
		'  make test            Run the unit test suite' \
		'  make smoke           Check the local CLI entry point' \
		'  make compose-config  Validate Docker Compose configuration' \
		'  make deploy          Build and start daemon, Prometheus, and Grafana' \
		'  make verify          Check daemon, Prometheus, Grafana, and scrape status' \
		'  make logs            Follow Docker Compose logs' \
		'  make stop            Stop the Docker Compose stack' \
		'  make rollback        Stop the stack and remove local data volumes' \
		'  make notify-test     Send a desktop notification test' \
		'  make install-shim    Install the host Codex PATH shim explicitly' \
		'  make uninstall-shim  Remove the host Codex PATH shim'

install-dev:
	$(PYTHON) -m pip install -e .

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

smoke:
	PYTHONPATH=src $(PYTHON) -m codex_speed --version

compose-config:
	$(COMPOSE) config

deploy:
	$(COMPOSE) up -d --build

verify:
	$(PYTHON) scripts/verify_stack.py

logs:
	$(COMPOSE) logs -f

stop:
	$(COMPOSE) down

rollback:
	$(COMPOSE) down -v --remove-orphans

notify-test:
	PYTHONPATH=src $(PYTHON) -m codex_speed notify-test

install-shim:
	PYTHONPATH=src $(PYTHON) -m codex_speed install-shim

uninstall-shim:
	PYTHONPATH=src $(PYTHON) -m codex_speed uninstall-shim
