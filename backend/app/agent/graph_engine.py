# FILE: backend/app/agent/graph_engine.py
"""A minimal, faithful LangGraph-compatible state-graph engine.

Why this exists: the target design mandates a LangGraph workflow, but this build
runs in an environment where the `langgraph` package cannot be installed. Rather
than fake it, we implement a small engine that mirrors LangGraph's public API
surface used by our workflow:

    StateGraph(state_schema)
        .add_node(name, fn)
        .add_edge(a, b)
        .add_conditional_edges(src, router_fn, {label: dst})
        .set_entry_point(name)
        .compile() -> CompiledGraph
    CompiledGraph.invoke(state) -> final_state

Node functions take the state dict and return a partial dict that is merged into
the state (exactly like LangGraph). Routing is explicit via edges / conditional
edges. `END` is the terminal sentinel.

Because our workflow only depends on this subset, swapping to the real library is
a one-line import change:  `from langgraph.graph import StateGraph, END`.
"""
from __future__ import annotations

from collections.abc import Callable, Hashable
from typing import Any

END = "__end__"

NodeFn = Callable[[dict], dict]
RouterFn = Callable[[dict], Hashable]


class StateGraph:
    def __init__(self, state_schema: type | None = None) -> None:
        self.state_schema = state_schema
        self._nodes: dict[str, NodeFn] = {}
        self._edges: dict[str, str] = {}
        self._cond: dict[str, tuple[RouterFn, dict[Hashable, str]]] = {}
        self._entry: str | None = None

    def add_node(self, name: str, fn: NodeFn) -> "StateGraph":
        if name in self._nodes:
            raise ValueError(f"Duplicate node: {name}")
        self._nodes[name] = fn
        return self

    def add_edge(self, src: str, dst: str) -> "StateGraph":
        self._edges[src] = dst
        return self

    def add_conditional_edges(self, src: str, router: RouterFn,
                              mapping: dict[Hashable, str]) -> "StateGraph":
        self._cond[src] = (router, mapping)
        return self

    def set_entry_point(self, name: str) -> "StateGraph":
        self._entry = name
        return self

    def compile(self) -> "CompiledGraph":
        if self._entry is None:
            raise ValueError("entry point not set")
        return CompiledGraph(self)


class CompiledGraph:
    def __init__(self, g: StateGraph) -> None:
        self._g = g

    def invoke(self, state: dict, *, max_steps: int = 100) -> dict:
        """Run the graph to completion, merging each node's partial output."""
        g = self._g
        current: str | None = g._entry
        steps = 0
        while current is not None and current != END:
            if steps > max_steps:
                raise RuntimeError(f"graph exceeded {max_steps} steps (cycle?)")
            steps += 1
            fn = g._nodes[current]
            partial = fn(state) or {}
            if not isinstance(partial, dict):
                raise TypeError(f"node '{current}' must return a dict, got {type(partial)}")
            state.update(partial)
            # Determine next node: conditional edges take precedence.
            if current in g._cond:
                router, mapping = g._cond[current]
                label = router(state)
                if label not in mapping:
                    raise KeyError(f"router for '{current}' returned unmapped label {label!r}")
                current = mapping[label]
            elif current in g._edges:
                current = g._edges[current]
            else:
                current = END
        return state


def get_state_graph() -> tuple[Any, str]:
    """Return (StateGraph, END), preferring the real langgraph if present.

    This makes the workflow genuinely portable: install langgraph and this
    function transparently returns the real implementation.
    """
    try:  # pragma: no cover - exercised only when langgraph is installed
        from langgraph.graph import END as LG_END  # type: ignore
        from langgraph.graph import StateGraph as LGStateGraph  # type: ignore
        return LGStateGraph, LG_END
    except Exception:
        return StateGraph, END
