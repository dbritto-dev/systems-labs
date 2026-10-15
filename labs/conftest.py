"""After `uv run pytest labs/<lab>`: a line per lab with your progress, stage by stage (from the
`@your_code(stage, ...)` tests: x is not yet, X is done). Not shown with LABS_REFERENCE=1."""

import re
from collections import defaultdict

from core.testing import REFERENCE

STAGE = re.compile(r"stage (\d+) of main\.py")


def pytest_terminal_summary(terminalreporter):
    if REFERENCE:
        return
    from core.i18n import catalog

    tx = catalog("core.text")
    per_lab: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # stage: [done, all]
    for outcome, done in (("xfailed", False), ("xpassed", True)):
        for report in terminalreporter.stats.get(outcome, []):
            match = STAGE.search(getattr(report, "wasxfail", "") or "")
            parts = report.nodeid.split("/")
            if not match or len(parts) < 2 or parts[0] != "labs":
                continue
            cell = per_lab[parts[1]][int(match.group(1))]
            cell[0] += done
            cell[1] += 1
    if not per_lab:
        return
    terminalreporter.section(tx.STAGES_TITLE)
    for lab in sorted(per_lab):
        stages = "  ".join(
            tx.STAGE_DONE.format(n=n) if done == total else tx.STAGE_PART.format(n=n, done=done, total=total)
            for n, (done, total) in sorted(per_lab[lab].items()))
        terminalreporter.write_line(tx.STAGE_ROW.format(lab=lab, stages=stages))
