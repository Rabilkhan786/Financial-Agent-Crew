# Convenience wrappers around uv. Run e.g. `make test`.
# On Windows, run these from Git Bash, or just run the underlying `uv run ...`.

.PHONY: install test lint demo eval baseline app gate0 gate3 clean

install:      ## Create/refresh the environment from the lockfile
	uv sync

test:         ## Run the test suite (all mocked, no API calls)
	uv run pytest -q

lint:         ## Lint with ruff
	uv run ruff check .

gate0:        ## GATE 0: check all four APIs + tracing are reachable
	uv run python check_gate0.py

gate3:        ## GATE 3: print the three specialists' findings for a ticker (default AAPL)
	uv run python demo_gate3.py AAPL Apple

baseline:     ## Run the single-LLM baseline over the question set (needs keys)
	uv run python -m eval.baselines.single_llm_search

eval:         ## Full eval: baseline vs InvestPanel (needs keys)
	uv run python -m eval.run_eval

demo:         ## Analyze one company from the CLI (needs keys)
	uv run python run.py "Is Apple a reasonable long-term investment?"

app:          ## Launch the Streamlit app (needs keys)
	uv run streamlit run app.py

clean:        ## Remove caches (keeps the venv and the lockfile)
	rm -rf .pytest_cache .ruff_cache .pytest_tmp
