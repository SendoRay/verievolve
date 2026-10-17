"""Prototype for LLM-driven adaptive-granularity search over primitive programs."""

__all__ = ["ActionKind", "HierExperiment"]


def __getattr__(name):
    if name == "ActionKind":
        from .model import ActionKind

        return ActionKind
    if name == "HierExperiment":
        from .controller import HierExperiment

        return HierExperiment
    raise AttributeError(name)
