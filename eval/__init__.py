"""Evaluation harness: the held-out question set, metrics, baselines, and runner.

This whole package exists before any agent, on purpose: without a way to measure,
there is no way to know whether the multi-agent panel actually beats a simple
baseline. Build order is data + evaluation first, agents second.
"""
