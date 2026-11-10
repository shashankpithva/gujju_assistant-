# Gujarati survey caller

Phones each number in a sheet, asks about the water supply in Gujarati (name, age, village, taluka, district, whether water comes, how often, and for how long each day), writes every answer into the sheet as it's given, and hangs up. The full guide is [docs/agent.md](../docs/agent.md).

```sh
uv sync && uv run pytest -q                     # works with no keys
cp .env.example .env                            # then add the keys: docs/agent.md, Set up
uv run python -m agent.main download-files      # once
uv run python -m agent.main console             # try the survey yourself, in this terminal

uv run python -m agent.dialer check             # is everything ready for real calls?
uv run python -m agent.main dev                 # terminal 1: the agent, waiting for calls
uv run python -m agent.dialer call +91...       # terminal 2: call one number (yours first)
uv run python -m agent.dialer run               # terminal 2: call everyone in the sheet
uv run python -m agent.report                   # end of the month: the report, as a tab in the sheet
```
