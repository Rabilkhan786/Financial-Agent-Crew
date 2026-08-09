# Architecture

InvestPanel is a multi-agent research panel. A **manager** sets the scope, three
**specialists** research in parallel, an **analyst** cross-checks whether their
findings actually agree, loops back once or twice if they don't, and then writes
the report. It produces **informational analysis, never investment advice.**

## Flow

```
Investment question
        |
   [Manager]  sets scope: company, ticker, competitors (found via real search), time window
        |
        +-------------------+-------------------+
        v                   v                   v
   [Financial]          [News]              [Risk]
   FMP fundamentals     Tavily search       volatility + drawdown,
   (numbers computed    + real article      computed in pure Python
    in Python)          fetch + summary     from the price history
        |                   |                   |
        +-------------------+-------------------+
                            |
                       [Analyst]
              does the numeric story match the
              qualitative story? any contradiction?
                            |
             yes -> route ONE specific follow-up
                    to ONE specialist (max 2 rounds)
             no  -> write the report
                            |
                            v
                        [Report]  (always ends with the disclaimer)
```

## Design decisions

| Decision | Reason |
|---|---|
| Three specialists run in parallel | They're independent until the cross-check; running them sequentially only adds latency with no benefit. In LangGraph the manager fans out to all three and they fan back in to the analyst. |
| The Risk agent has no separate API | Volatility and drawdown are computable from the price history the system already fetched (`tools/volatility.py`). A separate "risk data" API would be redundant. |
| The Analyst never just merges — it must find and act on contradictions | This is the entire point. Without it, the system is three parallel LLM calls plus a summary — the same thing one LLM with search could produce in a single pass. The cross-check is built as explicit field-level detectors (`agents/analyst.py`), not a vague "does this feel consistent?" prompt. |
| Max 2 follow-up rounds | Keeps cost and latency bounded and forces a conclusion even with imperfect information — like a real analyst working to a deadline. The bound lives in `config.MAX_FOLLOWUP_ROUNDS`. |
| Financial numbers are computed in Python, never by the LLM | A figure like "revenue growth = 12%" traces straight back to an FMP field and cannot be hallucinated. The LLM only writes prose. |
| The disclaimer is a hardcoded, validator-forced field | Removes any chance an agent omits or weakens it under prompt pressure. |
| No MCP | A deliberate simplification: direct HTTP calls with httpx are easier to build, debug, and explain. Documented, not accidental. |

## Build order (why the eval came before the agents)

Data loaders and the evaluation harness were built **before** the agents, and the
baseline **before** the panel. Without a baseline and a metric, there is no way to
know whether the multi-agent panel actually helps — so the project is set up to
measure that honestly, even if the answer turns out to be "it doesn't".
