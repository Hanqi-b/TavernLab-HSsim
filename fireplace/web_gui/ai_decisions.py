"""Private, JSON-only diagnostics; deliberately outside replay/public state."""

import json
from collections.abc import Mapping


def capture_decision(agent, action, *, action_seq, turn, seat):
    """Detach one diagnostic row without making diagnostics a gameplay error."""
    stats = getattr(agent, "last_search_stats", {})
    trace = stats.get("decision_trace") if isinstance(stats, Mapping) else None
    reason = "trace_unavailable"
    if isinstance(trace, Mapping):
        try:
            encoded = json.dumps(dict(trace), ensure_ascii=False, allow_nan=False)
            if len(encoded.encode("utf-8")) > 262144:
                reason = "trace_size_limit"
            else:
                trace = json.loads(encoded)
                selected = trace.get("selected_action")
                if selected is not None and selected != action.to_dict():
                    reason = "stale_trace"
                else:
                    return {"action_seq": action_seq, "turn": turn, "seat": seat,
                            "action": action.to_dict(), "trace": trace}
        except (TypeError, ValueError, OverflowError):
            reason = "trace_not_json_safe"
    return {"action_seq": action_seq, "turn": turn, "seat": seat,
            "action": action.to_dict(), "trace": {
                "policy_version": getattr(agent, "policy_version", None),
                "selected_action": action.to_dict(), "reason": reason,
                "candidates": [], "complete": False}}


def restore_decisions(metadata):
    """Old archives have no diagnostics; new rows survive resume verbatim."""
    rows = metadata.get("ai_decisions", []) if isinstance(metadata, Mapping) else []
    if not isinstance(rows, list):
        raise ValueError("invalid private AI decision diagnostics")
    # Archive storage already validates JSON; roundtrip avoids sharing mutable
    # diagnostic references with the loaded envelope.
    return json.loads(json.dumps(rows, allow_nan=False))


def trim_decisions(rows, *, max_rows=512, max_bytes=4 * 1024 * 1024):
    """Keep recent diagnostics within a per-match bound; report lost rows."""
    sizes = [len(json.dumps(row, ensure_ascii=False, allow_nan=False).encode("utf-8")) for row in rows]
    total = sum(sizes)
    dropped = 0
    while dropped < len(rows) and (len(rows) - dropped > max_rows or total > max_bytes):
        total -= sizes[dropped]
        dropped += 1
    if dropped:
        del rows[:dropped]
    return dropped
