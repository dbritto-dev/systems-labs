"""Every lab's reference solution, on long runs: 30 simulated minutes on 3 seeds, every settled goal OK.

The lab tests check the first minutes; a run never restarts, so a goal that only fails after 20
minutes (a budget that has run dry, a rare clump of traffic, a measure that drifts) would only show
in the viewer. Slow (a few minutes with every core busy), so it is skipped unless LABS_SLOW=1:

    LABS_SLOW=1 uv run pytest labs/test_long_runs.py
"""

import os
from concurrent.futures import ProcessPoolExecutor

import pytest

from core.contract import discover
from core.testing import SLOW, settled_alerts

MINUTES = 30
SEEDS = (1, 2, 3)
LABS = sorted(discover())

pytestmark = [pytest.mark.slow, pytest.mark.skipif(not SLOW, reason="a long run: set LABS_SLOW=1")]


@pytest.fixture(scope="module")
def alerts(request):
    """The selected (lab, seed) runs, all started at once on every core; each test waits for its own."""
    jobs = sorted({(item.callspec.params["lab"], item.callspec.params["seed"]) for item in request.session.items
                   if item.module is request.module and hasattr(item, "callspec")})
    pool = ProcessPoolExecutor(max_workers=os.cpu_count())
    yield {job: pool.submit(settled_alerts, job[0], "reference", MINUTES, job[1]) for job in jobs}
    pool.shutdown(cancel_futures=True)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("lab", LABS)
def test_the_reference_passes_every_goal_for_30_minutes(alerts, lab, seed):
    found = alerts[lab, seed].result()  # re-raises whatever the run raised
    assert not found, "\n".join(found)
