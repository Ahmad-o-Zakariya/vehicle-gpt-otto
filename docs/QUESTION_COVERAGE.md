# Question Coverage

The table records whether the selected data can answer the case-study questions. “Partial” describes coverage and does not support causal claims. Full evidence is in [`acceptance_report.json`](../data/manifests/acceptance_report.json).

| # | Question | Verdict | Available evidence | Main limit |
|---:|---|---|---|---|
| 1 | Why has driving range reduced over the last two weeks? | **PARTIALLY SUPPORTED** | 2017-11-05 to 2018-11-05; 293 trips, 191 active dates; final 14 days contain 10 trips on 7 dates. | No direct range or odometer signal; available battery/route values are proxies. Sparse daily use; no current-date data. |
| 2 | When did fuel efficiency show its largest drop? | **PARTIALLY SUPPORTED; EXPLORATORY ONLY** | 5 trips, 1,822 samples, 5 active dates; 2018-02-25 to 2018-10-26. | Too few trips for a robust longitudinal claim; no directly recorded fuel-economy metric or sufficiently dense repeated use. |
| 3 | Show all ADAS disengagement events from yesterday. | **UNSUPPORTED FOR YESTERDAY; HISTORICAL STATE TRANSITIONS PARTIALLY AVAILABLE** | 27 short clips; 25 have unix_time fields with repeated timestamps; registry spans 2023-11-21 to 2024-06-22. 55 real enable-state transitions (30 false→true, 25 true→false). | No data near 2026-11-05; state changes are not explicit OEM disengagement records and have no source reason codes; unix_time is repeated for many rows. |
| 4 | What happened before the battery overheating warning? | **PARTIALLY SUPPORTED FOR SYNTHETIC PIPELINE TESTING ONLY** | 70 measured trips, 10 Hz, 2019-06-25 to 2020-02-07; five seeded synthetic occurrences, four development and one held out; two untouched controls. | TUM has no pump-duty measurement and no real BATT_OVERTEMP event. Synthetic temporal precedence/recurrence is test evidence only, not causal evidence. |
| 5 | Compare energy consumption between city and highway driving. | **UNSUPPORTED** | VED Leaf has 293 trips and GPS; TUM has 70 trips but no GPS capability; comma segment is explicitly a highway segment but only one short RAV4 clip. | Cannot make a measured city-versus-highway comparison without unsupported inferred classes; one comma highway segment is not a comparison. |

## Interpretation

- **Range change (Q1):** exploratory proxies exist for the Leaf; there is no direct range or odometer channel, and the recent window is sparse.
- **Fuel efficiency (Q2):** only five measured diesel trips are available; any result is exploratory, not a robust longitudinal trend.
- **ADAS yesterday (Q3):** unsupported for the present date. OpenLKA observations are historical controller-state transitions without OEM reason codes; repeated Unix times weaken sample-level wall-clock ordering.
- **Overheating (Q4):** synthetic recurrence can validate pipeline behavior only. It does not establish a real failure or causal mechanism.
- **City versus highway (Q5):** unsupported; there are no verified city/highway labels or map-matched classifications.
