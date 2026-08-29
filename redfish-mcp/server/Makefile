PYTHON ?= python3

.PHONY: install install-dev lint typecheck test test-cov gate verify run-stdio run-http \
	build-index corpus-latest refresh-corpus

CORPUS_REF ?=

install:
	$(PYTHON) -m pip install -e .

install-dev:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(PYTHON) -m ruff check src tests tools scripts

typecheck:
	$(PYTHON) -m mypy src tests tools

test:
	$(PYTHON) -m pytest -q

test-cov:
	$(PYTHON) -m pytest --cov=mirastack_redfish_mcp --cov-report=term-missing --cov-report=xml

gate:
	$(PYTHON) scripts/check_tool_metadata.py
	$(PYTHON) scripts/check_corpus_conformance.py
	$(PYTHON) scripts/check_versions.py

verify: lint typecheck test gate

run-stdio:
	$(PYTHON) -m mirastack_redfish_mcp --transport stdio

run-http:
	$(PYTHON) -m mirastack_redfish_mcp --transport streamable-http --host 127.0.0.1 --port 8000

build-index:
	$(PYTHON) tools/build_schema_index.py --output src/mirastack_redfish_mcp/data/redfish_index.json.gz

corpus-latest:
	$(PYTHON) tools/redfish_corpus.py --check-latest

# Rebuild the index from a different DMTF release, e.g. `make refresh-corpus CORPUS_REF=2026.2`.
# Update CORPUS_REF in tools/redfish_corpus.py in the same change so the pin and the committed
# artifact stay in agreement; tests/test_corpus.py enforces that.
refresh-corpus:
	@test -n "$(CORPUS_REF)" || { echo "usage: make refresh-corpus CORPUS_REF=<tag>"; exit 2; }
	$(PYTHON) tools/build_schema_index.py --corpus-ref $(CORPUS_REF) --output src/mirastack_redfish_mcp/data/redfish_index.json.gz

