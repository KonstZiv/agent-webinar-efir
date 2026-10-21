"""The slice «лічильники й експорт»: the counters of the page, the statistics, the export.

``install`` provides the slice's services by key (``app.adapters.extras.keys``) and gives
``_counters.html`` its values (template global ``counters``). Every service is built on first
use; the reports read the shared tables through the application's engine. The polls of the
counters leave no line in the uvicorn access log.
"""

from app.adapters.extras.access_log import install_counter_polls_filter
from app.adapters.extras.keys import COUNTERS, REPORTS, STATISTICS
from app.adapters.extras.reports import SqlReportStore
from app.adapters.extras.view import CountersPartial
from app.core.extras.counters import CachedCounters
from app.core.extras.statistics import Statistics
from app.services import CLOCK
from app.slices import SliceSetup


def install(setup: SliceSetup) -> None:
    services = setup.services
    setup.provide(REPORTS, lambda: SqlReportStore(setup.engine()))
    setup.provide(COUNTERS, lambda: CachedCounters(services.get(REPORTS), services.get(CLOCK)))
    setup.provide(
        STATISTICS, lambda: Statistics(store=services.get(REPORTS), clock=services.get(CLOCK))
    )
    setup.template_global("counters", CountersPartial())
    install_counter_polls_filter()
