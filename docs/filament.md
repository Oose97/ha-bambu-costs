# How filament is priced

## RFID tags do the heavy lifting

The per-slot costing leans on Bambu Lab's **RFID spool tags**: the tray sensors report
each tag's serial, which is what scans spools into the library, prices a slot the moment
its spool is loaded, and keeps following the spool as it moves between slots. Cloned
RFID tags work exactly like originals — a serial is a serial.

**Generic (untagged) spools still work**, with one difference: there is no tag to price
them from, so for a per-slot cost you set the slot's own price number by hand — before
the print, or once it is running. The integration never overwrites that manual price
while a tagless spool sits in the slot (see below); it is cleared only when the slot is
actually emptied or a tagged spool takes its place. If you skip the manual step, the
slot is simply costed at the default filament price.

## How a slot gets its price

In order of precedence:

1. The **tag library**, matched on the `tag_uid` the tray reports — the price of the spool
   actually loaded. A spool carries a tag on each side reporting different serials, so a
   row can name the other one in `serial_2`; either matches, so it prices the same
   whichever way round the spool goes in.
2. The slot's own **price number**, if you have set one.
3. The **default filament price**.

Each row in the breakdown carries `price_source` so you can see which applied.

## When a slot's price entity updates

The price numbers track what is loaded rather than being settings you maintain. They are
rewritten **the moment a tray changes** — the tray sensors are watched, so loading a spool
prices the slot from its tag immediately, and unloading one drops it to **0**. They are
also refreshed when a print **starts** and when it **finishes**, and on demand via
`bambu_costs.sync_slot_prices`.

A slot holding a spool the library does not know also goes to 0. Zero means "no price of
its own", so costing falls back to the default rather than charging nothing.

Three cases are deliberately skipped instead of zeroed, because none of them means
empty: a slot with no tray sensor configured; a tray whose own state is `unavailable` —
usually the printer being switched off, which must not look like every spool was
unloaded; and a **loaded spool with no readable tag** — a generic spool. That last one
is what makes hand-priced generic spools workable at all: the sync runs on every tray
update, so zeroing there would wipe the manual price moments after it was typed in.

None of this affects what a print costs. The tag price is resolved live at calculation
time, so the figures are right even if these entities are stale.

Filament the printer counted that no configured slot claimed — an external spool, or a
slot whose attribute name drifted — becomes an `External` row priced at the default,
rather than being dropped. Mixed AMS + external jobs therefore total correctly.

## Scanned spools are added to the library

The same tray sensors carry newly read RFID tags, so loading a spool the library has never
seen **appends a row for it** instead of leaving you to type it in. The printer reports the
product name and colour but never a price, so the row starts at **0** — which reads as "no
price of its own" — and an `INFO` line in the log tells you to set it in the tags card.

The colour is named from Bambu's own palette (274 hexes, e.g. `#00AE42` → *Bambu Green
(10501)*). A third-party hex that isn't one of theirs is not an error; the row is added
with `Unknown Color` for you to rename.

Nothing is added for an empty tray, and re-reading a tag already in the library does
nothing. A serial named as some row's **`serial_2`** counts as already known — so if you
fill in a spool's second tag before scanning that side, it will not create a duplicate.
Leave `serial_2` blank and the second tag becomes its own row, which you can pair up later
by hand.

## Surviving a restart mid-print

A print weight sensor typically keeps its total across a Home Assistant restart but
loses the per-slot attributes until the next print begins. Left alone, the whole job
would fall through to the External branch and be repriced at the default — a
plausible-looking but wrong number, quietly written into the job log.

So the last breakdown computed from real per-slot data is persisted with the sensor. If
the attributes disappear while the job name and total weight still match that snapshot,
the remembered split is used and the breakdown carries `restored: true`.

It is deliberately conservative. A different job name or a changed total rejects the
snapshot, live attributes always win over it, an External-only result is never
remembered as good, and the snapshot is dropped the moment a new print starts so it can
never be applied to different filament. Prices are kept as they were rather than
re-resolved — the tray sensors lose their `tag_uid` in the same restart, so recomputing
would reintroduce the fallback this exists to avoid.
