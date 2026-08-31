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

## Scanned spools are added to the library

The tray sensors carry newly read RFID tags, so loading a spool the library has never
seen **appends a row for it** instead of leaving you to type it in. The printer reports
the product name and colour but never a price, so the row starts at **0** — which reads
as "no price of its own" — and an `INFO` line in the log tells you to set it in the tags
card.

The AMS is what makes this automatic, not what makes it possible: rows can also be added
by hand with **+ Row** in the tags card. If you can read a tag's UID some other way — a
phone's NFC reader will do — type it into the serial column and the spool prices itself
the same way the moment it is loaded.

The colour is named from Bambu's own palette, keyed by **material, product line and
hex** — the same colour carries a different filament code per line, so `#FFFFFF` scans
in as *Jade White (10100)* on a PLA Basic spool, *Ivory White (11100)* on PLA Matte and
*Pure White (17100)* on PLA Pure. The line is read from the spool's product name; the
material alone still narrows to the right family. Multi-colour filaments map every hex
of their gradient to the one name. A third-party hex that isn't Bambu's at all is
looked up on the [color-names](https://github.com/meodai/color-names) web API
(`api.color.pizza`) — one small request per newly scanned unknown spool, nothing else
ever goes online. The lookup can be turned off in the options; off, offline, or
failing, the row is added with `Unknown Color` for you to rename, exactly as before.

Nothing is added for an empty tray — or for a loaded spool with no readable tag. The
library only ever holds tagged spools: without a serial there is nothing to match a row
by later, and two generic spools cannot be told apart. (A "no tag" report in any of its
spellings — blank, `none`, `unknown`, `unavailable`, the all-zero UID — is recognised
case-insensitively.) Rows without a serial can still be typed into the tags card by
hand; they are inert for slot pricing but show in the calculator's filament list.
Re-reading a tag already in the library does nothing. A serial named as some row's
**`serial_2`** counts as already known — so if you fill in a spool's second tag before
scanning that side, it will not create a duplicate. Leave `serial_2` blank and the
second tag becomes its own row — and the shared
[spool id](#the-spool-id-learns-itself) pairs the two on the spot.

## How a slot gets its price

In order of precedence:

1. The **tag library**, matched on the `tag_uid` the tray reports — the price of the spool
   actually loaded. A spool carries a tag on each side reporting different serials, so a
   row can name the other one in `serial_2`; either matches, so it prices the same
   whichever way round the spool goes in.
2. The slot's own **price number**, if you have set one.
3. The **default filament price**.

Each row in the breakdown carries `price_source` so you can see which applied —
including `remembered`, for a spool that
[ran out mid-print](#when-a-spool-runs-out-mid-print).

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

## The spool id learns itself

Loading a spool is the one moment two identifiers are visible side by side: the RFID
tag the AMS just read, and the ``tray_uuid`` the printer reports for that spool — the
same id its cloud filament inventory uses. Whenever that happens, the id is recorded
on the matching library row's **Spool ID** column, hands-free. Only a blank is ever
filled: a value you typed or corrected stands, and the column is editable in the tags
card like any other.

The id also does the pairing chore. A spool carries a tag on each side, and until now
the second side either scanned in as a puzzling new row or had to be typed in by
hand. Now, when two rows turn out to share one spool id and **both** have an empty
second-serial slot, they are paired on the spot — the two sides found each other.
Rows already paired are never touched: that is also what keeps clone-tagged spools
safe, since several physical clones can share one cloud id without being stitched
together, each pairing only to its own other side. A newly scanned spool records its
id from the very first read.

## Remaining grams from the cloud inventory

Point the optional **filament inventory sensor** (found by discovery when the printer
integration provides one) at the printer cloud's spool inventory and the library
starts tracking **grams left per spool**, over the learned spool ids. Every inventory
update — a tray engaging, a print ending — refreshes the ``remaining_g`` of every row
carrying that spool's id, a pair's two rows together; nothing is written when nothing
changed, so the file is never churned.

Spools the library has never seen are **added to it**, serial-less but carrying their
spool id, product, colour (palette-named) and remaining grams. Two guards keep this
from littering: a row with the same product and colour that merely has not learned
its id yet blocks the seeding — it is almost certainly that spool, one load away from
linking up — and when a seeded spool is finally loaded, the scan **claims** the
seeded row (fills in its serial) instead of adding a twin.

The figures are the printer cloud's own estimates — good inventory, not billing data;
costing keeps using measured print weights. And a clone-tagged spool shares its cloud
identity with its source, so its remaining figure describes the cloud's merged
bookkeeping, not the physical spool.

### The tray's own figure, on load

The tray itself also reports a remaining **percentage** the moment it reads a spool.
With **no inventory sensor configured** that is the only remaining figure there is,
so loading a spool always writes it — as grams of an assumed **1 kg spool** — to
every row of the pair. With an inventory configured, the on-load figure is opt-in
via the **Always take remaining on load** switch (only offered then): the inventory
moves on the cloud's own bookkeeping events, while a fresh load is information right
now, so the switch writes the tray's estimate immediately — and the next inventory
reading overwrites it. The cloud stays the source of truth either way. A tray that
does not know (a spool without usable tag data reports −1) writes nothing.

## When a spool runs out mid-print

A spool that empties part-way through a job gets replaced, and the replacement is
often a bare one — no tag for the AMS to read. The slot goes from *known* to
*anonymous* while the same job is still printing, and the last thing that job needs is
to be repriced at the default and logged under a blank filament name.

So while a print runs, each slot's resolved spool — name, product, colour and price —
is remembered, and a slot whose tag stops reading falls back to it. The breakdown row
then carries `price_source: remembered`, so the substitution is visible rather than
silent. It survives a restart with the per-slot snapshot, and still applies when the
job is logged, which is the usual case: a spool tends to run out at the *end*, after
the print-end transition has already fired.

The memory is per print — a new job starts from what is actually loaded — and only
ever fills a gap. A slot whose tag still reads is priced live as always, a slot that
never had a tag keeps using its own price number, and swapping in a *different tagged*
spool prices from that new tag rather than the memory.

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
