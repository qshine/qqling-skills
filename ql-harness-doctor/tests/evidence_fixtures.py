"""Synthetic trace inputs for contract tests; never real execution proof."""


def synthetic_trace(file_id, first_line=1):
    refs = [dict(file_id=file_id, line=first_line + offset) for offset in range(3)]
    trace = dict(
        declarations=[refs[0]], execution_records=[refs[1]],
        result_checks=[dict(
            record=refs[1], observation=refs[2], method="record_cross_check",
            scope="Synthetic task and fixture revision only", checked_at="2026-09-13T10:00:00+08:00",
            outcome="confirmed", limitations="Synthetic contract fixture; no real task was executed.",
        )],
    )
    return refs, trace
