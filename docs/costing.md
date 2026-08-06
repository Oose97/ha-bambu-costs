# How electricity is costed

## Electricity price

Set **Electricity price sensor** to a sensor reporting the price per kWh and a variable
tariff is followed automatically — `sensor.electricity_price` at `0.22986 EUR/kWh` is the
shape this expects. The fixed **Electricity price** number stays as the fallback, used
whenever no sensor is configured or the sensor reads `unknown`/`unavailable`/non-numeric.

Negative prices are passed through rather than filtered, since spot tariffs can go
negative. The sensor's value is taken as-is, so it must already be per kWh in your
currency — point it at a template sensor if yours reports ct/kWh or EUR/MWh.

## Cost is integrated, not estimated

Set **Power sensors** and the integration keeps a live cost rate — summed watts × the
current price — and integrates it over time into `cost_total`. Because the rate is re-read
whenever the power or the price moves, and each interval is charged at the rate that
actually applied to it, a tariff that changes mid-print is charged as it changed. That
removes the approximation of multiplying total kWh by the price at the end.

Two consequences fall out of the accumulator running continuously:

- **A print's electricity** is the total's delta between start and finish, so it is exact
  even on a spot tariff. `log_job` uses it whenever power sensors are configured, falling
  back to kWh × price when they are not.
- **Standby is counted.** The gap between one print ending and the next starting is
  measured too, and lands in `last_idle_cost`. On a printer drawing ~14 W at rest that is
  easily larger than the prints themselves.
- **Every stretch is banked into `total_cost` exactly once.** `cost_at_print_end` doubles
  as a banked-through mark: idle windows are added when the next print starts (or on a
  reconnect resync), and a print's own stint is added when it ends — **aborted or not**,
  so a stopped print's electricity is not lost just because nothing logged it. `log_job`
  therefore adds only the filament to the total; with no power sensors configured there
  is no live banking, and the row's estimated power cost rides along instead. A resume
  banks nothing, so a recovered job cannot be charged twice.

Accrual is computed from elapsed time rather than tick count, so a missed or irregular
tick costs freshness, never accuracy.

## Losing sight of the printer

A printer prints perfectly well with Home Assistant not watching, and it re-announces its
state on reconnecting. `finish` is a state it then sits in indefinitely, so a reconnect
looks exactly like a job ending — and a reconnect mid-job looks exactly like one starting.
Neither is true, and both used to move the cost markers.

- **A finish with nothing running is a resync.** The idle window is moved forward and the
  standby accrued in it is *banked first* rather than dropped, and no print cost is
  recorded, because no print ended.
- **A start out of a disconnected state is decided by task name.** The same name means the
  job was already underway and its markers still apply; a different one means new work
  began unobserved. With no name to compare it counts as a resume — keeping stale markers
  overcharges one print by the idle before it, while discarding markers that were needed
  loses everything a running job had spent, with nothing left to rebuild it from.

Standby is banked in exactly one place, so no path can move the idle marker without
banking what the window held.

## When the power sensor stops reporting

Integrating power has one silent failure mode: a sensor that stops reporting integrates to
nothing. A smart plug that drops off the network for the length of a print produces a
confident-looking small number rather than visibly missing data.

An energy **counter** survives that — it keeps counting through the outage and its delta is
still right once it reconnects. So the integral is used, but checked against the counter at
the end of every job, and the counter wins when:

- **no print start was observed** — the printer went offline mid-job and came back
  reporting `finish`, so the window that was integrated belongs to an *earlier* job; or
- **the counter recorded materially more energy than the integral charged for.** The
  integral can only ever under-count this way, so the larger figure is the honest one.

Both cases log a `WARNING` naming both figures. Ordinary disagreement is expected — the
integral follows a moving tariff that a flat price cannot — so a 25% slack applies before
the second rule fires.

> **Point the energy sensor at a raw counter, not a `utility_meter`.** This matters more
> than it looks. When a source goes `unavailable`, `utility_meter` deliberately skips the
> delta across the gap: it cannot tell a genuine jump from a meter reset, so it drops the
> consumption instead of guessing. A plug's own lifetime `_energy` sensor keeps it. So a
> meter stacked on a counter can lose most of a print while the counter underneath it
> recorded the lot — and the meter is the one that looks like the tidier choice.

**Configure the power and energy lists over the same devices.** They are cross-checked
against each other, so metering three sockets while integrating one makes the metered
figure legitimately larger every time and the check fires on every job. Whichever set you
choose — printer only, or printer plus AMS plus a dryer — put the same sockets in both.

**After changing which energy sensors are configured, re-snapshot the start marker.** The
counters are cumulative and each one reads a different lifetime total, so swapping them
leaves `number.<name>_energy_at_print_start` pointing at a number from a different scale
and the next job computes an enormous delta. Set it to the new sum:

```yaml
action: number.set_value
target:
  entity_id: number.bambu_costs_energy_at_print_start
data:
  value: >-
    {{ (states('sensor.printer_socket_energy') | float(0)
      + states('sensor.ams_socket_energy') | float(0)) | round(6) }}
```

Forgetting is not catastrophic — a delta implying an average draw above 3 kW is rejected as
a counter discontinuity and the integral is kept, with an `ERROR` naming the figure — but
the guard is a backstop, not a substitute for re-snapshotting.

## Costs per month

The integration deliberately does **not** implement monthly cycles. Core's `utility_meter`
already does that — cycles, restarts, DST, offsets, tariffs — and reimplementing it here
would be a worse copy that only ever did one period.

What the integration provides is a source worth pointing it at:
`sensor.<name>_total_spend`, the whole bill with `state_class: total_increasing`. The
running figure lives in `number.<name>_total_cost` so it can be *seeded* when you cut over
from an older setup, and numbers carry no state class — nothing will meter or graph one.
This sensor is that number with the metadata attached.

```yaml
utility_meter:
  bambu_costs_monthly:
    source: sensor.bambu_costs_total_spend
    cycle: monthly
```

Check the entity ID before pasting that. If the integration's device is assigned to an
area, Home Assistant prefixes entities created *after* the assignment with the area slug,
while entities that existed before the move keep the unprefixed ID — so both forms can
coexist in one install.

Add `cycle: daily` or `yearly` blocks off the same source if you want them. Seed the
number **before** creating the meter, so the starting balance is not counted as this
month's spend:

```yaml
action: number.set_value
target:
  entity_id: number.bambu_costs_total_cost
data:
  value: 0  # whatever the old setup had spent to date
```
