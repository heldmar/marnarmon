# Docker Monitor — component spec (rev 2)

Developer-ready spec for the **Docker Monitor** section. It turns the approved
interactive mockup (`docker-monitor-mockup.html`, rev 2) into precise component,
CSS, state, and accessibility requirements. **This document does not authorize
new frontend dependencies** — everything here is hand-drawn SVG + CSS on the
existing token system, consistent with `dashboard/CLAUDE.md`.

Scope of this doc: visual/interaction contract only. It names the API surface
(`/api/docker/*`) but does not define the wire format — that belongs in
`API.md`. Where the developer needs a data shape to render a prop, the shape is
given as a UI-facing view model, not a promise about the HTTP payload.

---

## 0. Conventions & capability gating

- **New section id:** `"docker"`. `App.jsx` `section` state becomes
  `"resources" | "logs" | "docker"`; still a plain switch, **no router**
  (matches the existing two-section decision).
- **Capability-gated exactly like Server Logs.** The Docker rail item and view
  render only when `/health` reports `features.docker === true`. The host is the
  single source of truth — flip it off there and every dashboard drops the
  section with no redeploy. Mirror the `logsEnabled` prop pattern in `Sidebar`
  with a `dockerEnabled` prop.
- **Read-only, polling.** Follows the Logs precedent: a Live toggle drives
  `usePolling(..., { enabled: live })` plus a manual Refresh. Suggested interval
  var `DOCKER_REFRESH_SECONDS` (default 5), its own env var, shorter than the
  300s metrics interval — do not reuse `REFRESH_SECONDS`. Wire it into
  `config.js` / the entrypoint the same way as `LOGS_REFRESH_SECONDS`.
- **Reuse before adding.** Every gauge is the existing `Gauge`; cards are
  `.card`; the log drawer's toolbar reuses `.search`, `.input`, `.seg`,
  `.live-dot`, `.btn`. Only the classes explicitly marked **NEW** below are to
  be added to `styles.css`.

### New design tokens (add to `:root`, `:root[data-theme="dark"]`, and the light block)

Taken verbatim from the mockup. Docker brand tint, used **only** for the rail
icon, the header brand dot, and stack accents — never for utilisation state.

```css
/* dark (:root and :root[data-theme="dark"]) */
--whale: #2496ed;
--whale-soft: rgba(36, 150, 237, 0.14);

/* light (:root[data-theme="light"]) */
--whale: #1a7fd0;
--whale-soft: rgba(26, 127, 208, 0.1);
```

---

## 1. Component tree

```
App.jsx
└─ DockerView                     (new view; sibling of MetricsView/LogsView)
   ├─ Header                      (existing — reused as-is)
   ├─ DockerGauges                (3 aggregate gauges; wraps existing GaugeCard/Gauge)
   ├─ <div class="stats">…</div>  (quick-stat strip — inline, like MetricsView)
   ├─ <div class="card meters-legend">  (meter legend — inline)
   ├─ StackCard  (× N)            (collapsible per-compose-project card)
   │  └─ ContainerRow (× M)       (one grid row per container)
   │     └─ ResourceMeter (× 3)   (RAM, CPU util meters + Disk variant)
   └─ ContainerLogs               (drawer; rendered once, portal/overlay, driven by selected container)

Sidebar                          (existing — add whale item + tooltips to all items)
```

`DockerView` owns: the poll (`usePolling(getDockerOverview, …)`), the Live
toggle state, collapsed-stack state, and the `selectedContainer` for the log
drawer. Children are presentational.

---

## 2. `Sidebar` change (retrofit + new item)

### 2.1 New Docker rail item

Add a third item, gated on `dockerEnabled`:

```jsx
if (dockerEnabled) {
  items.push({ id: "docker", label: "Docker",
    desc: "Containers, stacks & live logs", icon: DockerIcon });
}
```

Also add a one-line `desc` to the two existing items so all three get tooltips:

| id | label | desc |
|----|-------|------|
| resources | Server Resources | CPU, memory, disk & network |
| logs | Server Logs | Browse the system journal |
| docker | Docker | Containers, stacks & live logs |

### 2.2 Finalized Docker whale icon (verbatim from mockup, cleaned)

Hand-drawn stroke SVG in the `Gauge.jsx`/`Sidebar.jsx` style. `stroke-width`
**1.6** (slightly finer than the 1.8 rail icons — the whale has more strokes).
`fill="none"` on the whale body; the container-stack cubes are stroked only.
`aria-hidden` because the `<button>` already carries the label.

```jsx
const DockerIcon = (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none"
       stroke="currentColor" strokeWidth="1.6"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {/* container stack */}
    <rect x="4"    y="9.5" width="2.6" height="2.4" />
    <rect x="7.2"  y="9.5" width="2.6" height="2.4" />
    <rect x="10.4" y="9.5" width="2.6" height="2.4" />
    <rect x="7.2"  y="6.8" width="2.6" height="2.4" />
    <rect x="10.4" y="6.8" width="2.6" height="2.4" />
    {/* whale body + wave */}
    <path d="M2.5 12.2h13.2c.9 0 1.7-.5 2.1-1.3.5.9 1.7 1.2 2.5.6-.1 1.9-1.3 4.6-4 5.3-1.1.3-2.2.4-3.3.4-4 0-7.4-2-9-5z" />
    {/* spout */}
    <path d="M19 8.6c.5-.4 1.3-.4 1.8 0-.2.5-.8.8-1.3.7" />
  </svg>
);
```

### 2.3 Tooltip markup (all three items)

Each `.sidebar-btn` becomes `position: relative` (already true in the mockup CSS)
and gains a `.tip` flyout as its **last child**. The tip shows on **hover AND
keyboard focus** (`:hover`, `:focus-visible`), so it is fully keyboard-reachable.

```jsx
<button
  className={`sidebar-btn${active ? " active" : ""}`}
  onClick={() => onSelect(it.id)}
  aria-label={it.label}
  aria-current={active ? "page" : undefined}
>
  {it.icon}
  <span className="tip" role="tooltip">
    <b>{it.label}</b>
    <i>{it.desc}</i>
  </span>
</button>
```

**Remove** the old native `title={it.label}` attribute — the `.tip` replaces it,
and keeping both double-renders a tooltip. The `aria-label` remains the
accessible name; `role="tooltip"` on the flyout is descriptive supporting text.

### 2.4 NEW CSS — `.tip`

```css
/* Rail tooltip flyout — appears on hover AND keyboard focus. */
.tip {
  position: absolute;
  left: calc(100% + 12px);
  top: 50%;
  transform: translateY(-50%) translateX(-4px);
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: var(--bg-elev);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 9px 12px;
  white-space: nowrap;
  text-align: left;
  box-shadow: var(--shadow);
  z-index: 60;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.14s ease, transform 0.14s ease;
}
.tip b { font-size: 13px; font-weight: 700; }
.tip i { font-size: 11.5px; font-style: normal; color: var(--text-dim); }
.tip::before {
  content: "";
  position: absolute;
  left: -5px;
  top: 50%;
  transform: translateY(-50%) rotate(45deg);
  width: 9px;
  height: 9px;
  background: var(--bg-elev);
  border-left: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}
.sidebar-btn:hover .tip,
.sidebar-btn:focus-visible .tip {
  opacity: 1;
  transform: translateY(-50%) translateX(0);
}
@media (prefers-reduced-motion: reduce) {
  .tip { transition: none; }
}
```

Also add, if not already present in the active-state rule, the whale accent for
the Docker item's active state (the mockup uses whale tint for active Docker):
the existing `.sidebar-btn.active` uses `--accent`. **Keep `--accent` for
active** to stay consistent with the other two rail items; do **not** special-case
the whale colour for active state. (The mockup tinted it whale for demo emphasis;
the production rail must treat all three items identically for active styling.)

---

## 3. `DockerView`

**Props:** `{ health, theme, onToggleTheme }` — identical signature to
`MetricsView` / `LogsView`.

**Renders (top → bottom):**
1. `<Header>` (host = `overview.host`, health pill, Refresh, theme toggle).
2. Docker daemon error banner (see states matrix) — `.banner.error`.
3. Loading `.center-msg` when first load and no data.
4. `<div className="section-label">Total consumed by all containers</div>`
5. `<DockerGauges totals={overview.totals} />`
6. Quick-stat strip (`.stats`) — inline.
7. `<div className="section-label">Stacks &amp; containers</div>`
8. Legend card (`.card.meters-legend`) — inline.
9. Empty `.center-msg` when zero containers, else `stacks.map(StackCard)`.
10. Footer note (`.muted`, centered) — "Polling every {n}s · read-only · /api/docker".
11. `<ContainerLogs>` (drawer overlay, always mounted, `open` driven by
    `selectedContainer`).

**View-model (what the poll resolves to — `getDockerOverview()`):**

```
overview = {
  host, dockerOk: bool, error: string|null,
  totals: {
    cpu:  { percent, usedCores, hostCores, foot },   // → gauge
    mem:  { percent, usedBytes, totalBytes, foot },   // → gauge
    disk: { percent, usedBytes, foot },               // → gauge (see 6.4)
  },
  stats: { running, stopped, stacks, netRxRate, netTxRate, restarts24h },
  stacks: [ StackVM… ],
}
```

**Existing tokens/classes used:** `.section-label` (NEW, see 3.3), `.stats`,
`.stat`, `.card`, `.center-msg`, `.banner.error`, `.muted`.

### 3.1 `DockerGauges`

**Props:** `{ totals }`.

**Renders:** `<div className="grid gauges">` with three `<GaugeCard>` (existing):

| title | value | footer (`.gauge-foot`, `strong` on the primary number) |
|-------|-------|--------|
| CPU | `totals.cpu.percent` | `<strong>{usedCores}</strong> of {hostCores} cores · {percent}% of host` |
| Memory | `totals.mem.percent` | `<strong>{fmtBytes(usedBytes)}</strong> of {fmtBytes(totalBytes)} used by containers` |
| Disk | `totals.disk.percent` | `<strong>{fmtBytes(usedBytes)}</strong> · images … · volumes … · logs …` |

All three use the existing 270° `Gauge` unchanged (size 132, stroke 12, `%`).
The gauge colour is the standard util scale (good/warn/bad at 60/85) — this is
**aggregate host pressure**, so utilisation colouring is correct here (unlike the
per-container disk meter, which is informational — see §6). Reuse `fmtBytes` /
`fmtRate` from `format.js`.

### 3.2 Quick-stat strip (inline in `DockerView`)

`<div className="stats">` with four `.stat` tiles. `.value` may contain a
`<small>` qualifier exactly as MetricsView does.

| label | value |
|-------|-------|
| Containers | `{running}` `<small>running · {stopped} stopped</small>` |
| Stacks | `{stacks}` |
| Net I/O | `{fmtRate(netRxRate)} ↓ · {fmtRate(netTxRate)} ↑` |
| Restarts (24h) | `{restarts24h}` |

### 3.3 NEW CSS — `.section-label` and `.meters-legend`

`.section-label` is used by both this view and could be adopted elsewhere; it is
new (not currently in `styles.css`).

```css
.section-label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-faint);
  margin: 4px 2px 12px;
}

/* Legend explaining the two meter semantics. Built on .card. */
.meters-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 16px 22px;
  align-items: center;
  padding: 10px 14px;
  margin-bottom: 14px;
  color: var(--text-dim);
  font-size: 12px;
}
.meters-legend .lg { display: inline-flex; align-items: center; gap: 7px; }
.meters-legend .sw { width: 22px; height: 8px; border-radius: 999px; }
.sw.util { background: linear-gradient(90deg, var(--good), var(--warn), var(--bad)); }
.sw.disk { background: var(--accent); }
.sw.nolim {
  background: repeating-linear-gradient(90deg, var(--grid) 0 6px, transparent 6px 12px);
  border: 1px solid var(--border);
}
```

Legend content (exact copy):
- `util` swatch — "RAM / CPU — fills toward each container's limit"
- `disk` swatch — "Disk — sized against the largest consumer (no limit applies)"
- `nolim` swatch — "no limit set"

---

## 4. `StackCard`

One card per Compose project. Collapsible; header shows a rollup + health badge.

**Props:**
```
{
  stack: {
    name, meta,                    // "blog", "WordPress + MariaDB + Redis"
    health: "ok"|"warn"|"bad",     // → badge variant
    healthLabel: string,           // "Healthy" | "1 unhealthy" | "1 stopped"
    memLabel, cpuLabel, diskLabel, // pre-formatted rollup strings
    containers: ContainerVM[],
  },
  collapsed: bool,
  onToggle: () => void,
  maxDisk: number,                 // largest container disk footprint IN VIEW (bytes) — passed down for meter scaling
  onViewLogs: (container) => void,
}
```

**Renders:** `<div className="card stack {collapsed?}">` containing a
`.stack-head` (role="button", `tabindex=0`, `aria-expanded`) and a `.stack-body`
that maps `containers` → `<ContainerRow>`.

Header layout (left→right): caret icon, cube stack icon (whale-coloured),
name + meta, spacer, `.stack-roll` (Memory / CPU / Disk rollups) + health
`.badge`.

**Health badge mapping (existing `.badge` variants):**

| stack.health | badge class | typical label |
|--------------|-------------|---------------|
| all containers ok | `badge ok` | "Healthy" |
| ≥1 unhealthy/restarting, none stopped | `badge warn` | "1 unhealthy" |
| ≥1 stopped | `badge bad` | "1 stopped" |

Rollup precedence when multiple conditions apply: **bad > warn > ok** (a stopped
container makes the whole stack badge `bad` even if others are healthy).

**Caret + cube icons (verbatim from mockup):**

```jsx
const Caret = (  // rotates -90° when collapsed via .stack.collapsed .stack-caret
  <svg className="stack-caret" viewBox="0 0 24 24" width="16" height="16"
       fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M6 9l6 6 6-6" />
  </svg>
);
const Cubes = (  // whale-coloured via .stack-icon
  <svg className="stack-icon" viewBox="0 0 24 24" width="18" height="18"
       fill="none" stroke="currentColor" strokeWidth="1.7"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 2l8 4.5v9L12 20l-8-4.5v-9L12 2z" />
    <path d="M12 20v-9" />
    <path d="M20 6.5L12 11 4 6.5" />
  </svg>
);
```

**Toggle behaviour:** click or Enter/Space on `.stack-head` toggles collapsed;
`aria-expanded` tracks state. Collapsed hides `.stack-body` and drops the header
bottom border (see CSS).

### 4.1 NEW CSS — stack card

```css
.stack { margin-bottom: 14px; padding: 0; overflow: hidden; }
.stack-head {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  cursor: pointer;
  user-select: none;
  border-bottom: 1px solid var(--border);
}
.stack-head:hover { background: var(--card-hover); }
.stack-head:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.stack-caret { color: var(--text-faint); transition: transform 0.18s; }
.stack.collapsed .stack-caret { transform: rotate(-90deg); }
.stack.collapsed .stack-body { display: none; }
.stack.collapsed .stack-head { border-bottom: 0; }
.stack-name { font-size: 15px; font-weight: 700; letter-spacing: 0.2px; }
.stack-icon { color: var(--whale); display: inline-flex; }
.stack-meta { color: var(--text-dim); font-size: 12.5px; margin-top: 1px; }
.stack-spacer { flex: 1; }
.stack-roll { display: flex; gap: 22px; align-items: center; }
.roll { text-align: right; }
.roll .k {
  font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.3px;
  color: var(--text-faint);
}
.roll .v {
  font-size: 14px; font-weight: 700;
  font-variant-numeric: tabular-nums; margin-top: 2px;
}

/* Health badges */
.badge {
  font-size: 10.5px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.3px; padding: 3px 9px; border-radius: 999px;
  border: 1px solid var(--border); white-space: nowrap;
}
.badge.ok   { color: var(--good); background: rgba(45, 212, 167, 0.12); }
.badge.warn { color: var(--warn); background: rgba(245, 181, 74, 0.12); }
.badge.bad  { color: var(--bad);  background: rgba(247, 109, 109, 0.12); }
```

> Note: `@media (prefers-reduced-motion: reduce)` should also zero the
> `.stack-caret` transition (add `.stack-caret` to the reduced-motion block).

@media (prefers-reduced-motion: reduce) additions:
```css
@media (prefers-reduced-motion: reduce) {
  .stack-caret { transition: none; }
  .meter > span { transition: none; }
}
```

---

## 5. `ContainerRow`

**Props:**
```
{
  container: {
    name, service,                 // "wordpress", "apache · wordpress:6.5"
    state: "ok"|"warn"|"bad",      // state-dot colour (see states matrix §7)
    mem:  { usedLabel, limitLabel|null, pct|null },
    cpu:  { usedLabel, limitLabel|null, pct|null },
    disk: { bytes, breakdown },    // breakdown = "rw 180 MB · volumes 1.2 GB"
  },
  maxDisk,                         // bytes — scale reference for disk meter
  onViewLogs: () => void,
}
```

**Renders:** `<div className="crow">` — a 5-column grid:
`[ name | RAM meter | CPU meter | Disk meter | action ]`.

Columns:
1. `.cname` — `.state-dot {state}` + name (`.n`) + service (`.svc`).
2. `<ResourceMeter kind="RAM" …/>`
3. `<ResourceMeter kind="CPU" …/>`
4. `<ResourceMeter variant="disk" …/>`
5. `.crow-actions` → "View logs" `.link-btn` (list icon + label), calls
   `onViewLogs`.

**View-logs button (verbatim icon):**
```jsx
<button className="link-btn" onClick={onViewLogs}
        aria-label={`View logs for ${container.name}`}>
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
       stroke="currentColor" strokeWidth="1.8"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 5h16" /><path d="M4 12h16" /><path d="M4 19h10" />
  </svg>
  View logs
</button>
```

### 5.1 NEW CSS — container row

```css
.stack-body { padding: 4px 8px 8px; }
.crow {
  display: grid;
  grid-template-columns: 188px 1fr 1fr 1fr auto;
  gap: 14px;
  align-items: center;
  padding: 13px 10px;
  border-top: 1px solid var(--border);
}
.crow:first-child { border-top: 0; }
.cname { display: flex; align-items: center; gap: 9px; min-width: 0; }
.state-dot { width: 9px; height: 9px; border-radius: 50%; flex: 0 0 auto; }
.state-dot.ok   { background: var(--good); box-shadow: 0 0 7px var(--good); }
.state-dot.warn { background: var(--warn); }
.state-dot.bad  { background: var(--bad); }
.cname .n {
  font-weight: 600; font-size: 13.5px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.cname .svc { color: var(--text-faint); font-size: 11.5px; margin-top: 1px; }

.crow-actions { display: flex; justify-content: flex-end; }
.link-btn {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 12.5px; font-weight: 600; color: var(--text-dim);
  background: transparent; border: 1px solid var(--border);
  border-radius: 8px; padding: 6px 10px; cursor: pointer;
}
.link-btn:hover { color: var(--text); background: var(--card-hover); }
.link-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
```

---

## 6. `ResourceMeter` (incl. disk variant)

A single component with two modes. **RAM/CPU** = used-vs-limit utilisation
meter; **disk** = informational footprint bar.

**Props:**
```
{
  kind: "RAM" | "CPU" | "Disk",   // meter label
  variant: "util" | "disk",        // default "util"
  // util mode:
  usedLabel, limitLabel|null, pct|null,   // pct null ⇒ "no limit set"
  // disk mode:
  bytes, maxDisk, breakdown,       // breakdown → ⓘ title
}
```

**Renders:** `.meter-label` row (`.mk` label + `.mv` value) above a
`.meter` track with a single `<span>` fill.

### 6.1 Meter semantics — thresholds & colour

| variant | fill colour | scale | thresholds |
|---------|-------------|-------|------------|
| util (RAM/CPU), limit set | `colorFor(pct)` | `pct` = used ÷ limit × 100, clamped `[2,100]` | good < 60 ≤ warn < 85 ≤ bad |
| util, **no limit** | none — hatched empty track | n/a | renders `.meter.nolimit` (hatched), fill `transparent`, label shows "no limit" | 
| disk | `var(--accent)` (blue) | `bytes ÷ maxDisk × 100`, clamped `[2,100]` | **none** — never coloured by threshold |

`colorFor` is the **same** function as `Gauge.jsx` (good/warn/bad at 60/85) —
reuse it, do not duplicate the numbers:

```js
function colorFor(v) {
  return v >= 85 ? "var(--bad)" : v >= 60 ? "var(--warn)" : "var(--good)";
}
```

**Why disk is blue, not util-coloured:** a container's disk footprint has **no
limit** to fill toward, so a red "high" reading would be meaningless. The disk
bar is a *relative* size cue — each container's footprint against the largest
consumer currently in view. It uses `--accent` (blue) to read as
informational, deliberately outside the good/warn/bad utilisation language. This
is the single most important semantic in the section; the legend states it
explicitly.

### 6.2 Disk bar scaling

`maxDisk` = the largest single-container disk footprint across **all containers
currently rendered** (compute once in `DockerView`, pass down). Each disk fill
width = `max(2, round(bytes / maxDisk × 100))%`. The 2% floor keeps a sliver
visible for tiny consumers. The value label uses `fmtBytes(bytes)`; the limit
slot is replaced by an `ⓘ` whose `title` is `breakdown`
(e.g. "rw 180 MB · volumes 1.2 GB").

### 6.3 "No limit" hatched style

When `pct === null` (util mode), the track gets the `.nolimit` modifier: a
repeating hatch of `--grid`, and the fill span is `transparent` at full width.
The value reads `{usedLabel} / no limit`, with "no limit" in the dimmed `em`
style. See CSS below.

### 6.4 Aggregate Disk gauge (§3.1) vs per-container disk meter

These differ on purpose: the **aggregate Disk gauge** (DockerGauges) *does* show
a percent-of-host and uses the util colour scale, because at the host level there
IS a total disk to fill. The **per-container** disk meter has no such reference,
hence the blue relative bar. Do not unify them.

### 6.5 NEW CSS — meters

```css
.meter-label {
  display: flex; justify-content: space-between;
  font-size: 11.5px; margin-bottom: 5px;
}
.meter-label .mk {
  color: var(--text-faint); text-transform: uppercase;
  letter-spacing: 0.3px; font-weight: 600; font-size: 10.5px;
}
.meter-label .mv {
  color: var(--text); font-weight: 600; font-variant-numeric: tabular-nums;
}
.meter-label .mv em { color: var(--text-dim); font-style: normal; font-weight: 500; }

.meter {
  height: 8px; border-radius: 999px;
  background: var(--grid); overflow: hidden; position: relative;
}
.meter > span {
  display: block; height: 100%; border-radius: 999px;
  transition: width 0.5s ease;
}
.meter.nolimit {
  background: repeating-linear-gradient(90deg, var(--grid) 0 6px, transparent 6px 12px);
}
/* disk: informational (no limit) — blue, not the util scale */
.meter.disk > span { background: var(--accent); }
```

(RAM/CPU util fills set `background` inline from `colorFor(pct)`; disk fill
colour comes from the `.meter.disk > span` rule above.)

---

## 7. `ContainerLogs` drawer

Right-side slide-over showing one container's live log tail. Reuses the Logs
section's toolbar vocabulary but is a **modal drawer**, not an inline panel.

**Props:**
```
{
  open: bool,
  container: { name, stack, image } | null,   // header title/subtitle
  onClose: () => void,
}
```
Internally owns: search filter text, tail size (`100 | 500 | 1000`), Live toggle,
and its own poll of `getContainerLogs(name, { tail, q })` gated on
`open && live`.

**Renders:** `.drawer-scrim` (fixed, click-outside to close) wrapping
`<aside className="drawer" role="dialog" aria-label="Container logs">`:

- **`.drawer-head`** — title (`container.name`), subtitle
  (`stack: {stack} · image: {image}`), spacer, Live `.btn` (reuses `.live-dot`),
  close `.icon-btn` ("✕", `aria-label="Close logs"`).
- **`.drawer-toolbar`** — `.search` (reuse existing `.search`/`.input` +
  SearchIcon from LogsView) with placeholder "Filter this container's log
  lines…"; a `.seg` tail-size group (reuse existing `.seg`), role="group"
  `aria-label="Tail size"`, buttons 100 / 500 / 1000 (500 default `.active`).
- **`.term`** — monospace scroll region; each line is a `.lrow`
  (`[ .lts timestamp | .lmsg message ]`). Severity spans:
  `.m-info/.m-warn/.m-err/.m-ok` + `.dim` for de-emphasis.
- **`.drawer-foot`** — left: "Showing last {tail} lines · {streaming|paused}";
  right: "timestamps in local time".

**Interaction:**
- Opens when a row's View logs is clicked (`DockerView` sets
  `selectedContainer`).
- Closes on: `.icon-btn` ✕, click on scrim backdrop (not the drawer body),
  **Escape** key.
- Auto-scrolls to bottom on new lines while Live is on.
- Live toggle here is independent of the page-level Live toggle.

### 7.1 NEW CSS — drawer

```css
.drawer-scrim {
  position: fixed; inset: 0; background: rgba(4, 7, 12, 0.55);
  display: none; align-items: stretch; justify-content: flex-end; z-index: 40;
}
.drawer-scrim.open { display: flex; }
.drawer {
  width: min(760px, 94vw); background: var(--bg);
  border-left: 1px solid var(--border);
  display: flex; flex-direction: column;
  box-shadow: -20px 0 50px rgba(0, 0, 0, 0.4);
}
.drawer-head {
  display: flex; align-items: center; gap: 12px;
  padding: 16px 20px; border-bottom: 1px solid var(--border);
}
.drawer-head .dh-title { font-size: 15px; font-weight: 700; }
.drawer-head .dh-sub { color: var(--text-dim); font-size: 12px; margin-top: 1px; }
.drawer-spacer { flex: 1; }

.icon-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 34px; height: 34px; border-radius: 9px;
  border: 1px solid var(--border); background: var(--bg-elev);
  color: var(--text-dim); cursor: pointer;
}
.icon-btn:hover { color: var(--text); background: var(--card-hover); }
.icon-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

.drawer-toolbar {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 12px 20px; border-bottom: 1px solid var(--border);
}
.term {
  flex: 1; overflow-y: auto; padding: 12px 18px;
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
  font-size: 12.5px; line-height: 1.6; background: var(--bg);
}
.lrow { display: grid; grid-template-columns: 84px 1fr; gap: 12px; padding: 1.5px 0; }
.lts { color: var(--text-faint); white-space: nowrap; font-variant-numeric: tabular-nums; }
.lmsg { color: var(--text); white-space: pre-wrap; word-break: break-word; }
.lmsg .m-info { color: var(--text); }
.lmsg .m-warn { color: var(--warn); }
.lmsg .m-err  { color: var(--bad); }
.lmsg .m-ok   { color: var(--good); }
.lmsg .dim    { color: var(--text-dim); }
.drawer-foot {
  display: flex; align-items: center; gap: 10px; justify-content: space-between;
  padding: 10px 20px; border-top: 1px solid var(--border);
  color: var(--text-faint); font-size: 12px;
}
```

> `.search`, `.input`, `.seg`, `.seg button.active`, `.btn`, `.live-dot` are
> **existing** — reuse verbatim, do not redefine.

---

## 8. States matrix

Every visual state and exactly how it renders. Reuses existing
`.badge`, `.state-dot`, `.banner.error`, `.center-msg`.

### 8.1 Container-level (`.state-dot` + row rendering)

| State | `state-dot` | RAM/CPU meters | Notes |
|-------|-------------|----------------|-------|
| **running (healthy)** | `.ok` (green, glow) | util-coloured fill vs limit | normal |
| **unhealthy** (healthcheck failing) | `.warn` (amber) | meters render as normal from last stats | service line may note "unhealthy"; dot is the signal |
| **restarting** | `.warn` (amber) | meters render last-known values | service line "restarting"; treat as warn |
| **stopped / exited** | `.bad` (red) | RAM/CPU pct = 0 → fill at 2% floor, colour green(0<60) but values read "0 B / limit", "0.00 cores / limit" | service line shows "· stopped"; still lists disk footprint (volumes persist) |
| **no limit set** (running) | per running state | util meter → `.meter.nolimit` hatched, value "{used} / no limit" | applies per-resource (a container may have a RAM limit but no CPU limit) |

For **stopped**, the dot is `bad` but the util fill (pct 0) is technically
"green". That is fine — the **dot** communicates lifecycle state; the **meter**
communicates utilisation. Do not force the meter red on stop.

### 8.2 Stack-level (`.badge`)

| State | badge | label example |
|-------|-------|---------------|
| **all healthy** | `.badge.ok` | "Healthy" |
| **degraded** (≥1 unhealthy/restarting, none stopped) | `.badge.warn` | "1 unhealthy" |
| **has stopped** (≥1 exited) | `.badge.bad` | "1 stopped" |

Precedence bad > warn > ok. Rollup Mem/CPU/Disk always show (sum across
containers, stopped included for disk since volumes persist).

### 8.3 View-level

| State | Render |
|-------|--------|
| **loading** (first load, no data) | `<div className="center-msg">Loading containers…</div>` (after Header) |
| **empty** (daemon OK, zero containers) | `<div className="center-msg">No containers are running on this host.</div>` — gauges/stats may still render as zeros, or suppress the stacks region and show only this message |
| **daemon unreachable** (`dockerOk === false` / error) | `<div className="banner error">Docker daemon unreachable{error ? ": " + error : ""}.<div className="muted">API: {config.apiBaseUrl}/docker</div></div>` above the (stale or absent) content, mirroring MetricsView's error banner |
| **capability off** (`features.docker !== true`) | Rail item absent; if somehow routed here, `<div className="center-msg">Docker monitoring isn't enabled on this host.</div>` (parallels the Logs `logs_disabled` copy) |

The header `HealthPill` continues to reflect `/health`; a Docker-specific "Docker
OK / unreachable" indicator is optional and, if added, uses the existing `.pill`
with `.led` (green `--good` when ok). Not required for v1.

---

## 9. Responsive rules

The 3-meter row reflows at two breakpoints already prototyped in the mockup.
Codify exactly:

```css
@media (max-width: 820px) {
  /* Container row: name spans full width, three meters share a row below it */
  .crow { grid-template-columns: 1fr 1fr 1fr; row-gap: 12px; }
  .cname { grid-column: 1 / -1; }
  .crow-actions { grid-column: 1 / -1; justify-content: flex-start; }
  /* Stack header rollup tightens; hide the CPU rollup, keep Memory + Disk */
  .stack-roll { gap: 14px; }
  .stack-roll .roll:nth-child(2) { display: none; }
}

@media (max-width: 560px) {
  /* Meters stack vertically, one per line */
  .crow { grid-template-columns: 1fr; }
  /* Hide the whole rollup on the stack header; the badge stays (it's after .stack-roll — see note) */
  .stack-roll { display: none; }
  /* Legend goes vertical */
  .meters-legend { flex-direction: column; align-items: flex-start; gap: 8px; }
}
```

**Implementation note on the 560px badge:** in the mockup the health `.badge`
lives *inside* `.stack-roll`, so `display:none` would hide it too. For
production, **render the `.badge` as a sibling of `.stack-roll`** (direct child
of the header) so the badge survives at ≤560px while the numeric rollup hides.
i.e. header children order: `caret, icon, name/meta, spacer, .stack-roll, .badge`.

Rail/shell responsiveness (`.sidebar` collapse at ≤640px) is already handled by
the existing `styles.css` media block — no change needed.

---

## 10. Accessibility

- **Rail tooltips:** shown on `:hover` AND `:focus-visible` so keyboard users
  get them; `role="tooltip"` on the flyout; the `<button>`'s `aria-label` is the
  accessible name; `aria-current="page"` on the active item. Icons are
  `aria-hidden`. Transitions disabled under `prefers-reduced-motion`.
- **Stack header:** `role="button"`, `tabindex=0`, `aria-expanded` reflecting
  collapsed state; Enter/Space toggles; visible `:focus-visible` outline
  (offset `-2px` so it stays inside the card radius).
- **Meters:** each `.meter` should carry `role="meter"` (or `img`) with an
  `aria-label` summarising the reading, e.g. `aria-label="RAM 612 MB of 1.0 GB,
  60%"`, or for disk `aria-label="Disk 1.4 GB"`. The ⓘ breakdown must be
  reachable as text (title + `aria-label`), not colour-only.
- **State is never colour-only:** the `.state-dot` colour is backed by the
  service-line text (e.g. "· stopped", "restarting") and the stack `.badge`
  text label, so red/green isn't the sole signal.
- **Gauges:** reuse `Gauge`'s existing `role="img"` + `aria-label="{n}%"`.
- **Drawer:** `role="dialog"` + `aria-label="Container logs"`; Escape closes;
  focus should move into the drawer on open and return to the triggering
  View-logs button on close; the ✕ and Live controls are real `<button>`s with
  `aria-label`s.
- **Live toggles:** `aria-pressed` reflecting on/off (matches LogsView's Live
  button).
- **Reduced motion:** `.tip`, `.stack-caret`, and `.meter > span` transitions
  are disabled under `prefers-reduced-motion: reduce`.
- **Focus-visible:** every new interactive element (`.link-btn`, `.icon-btn`,
  `.stack-head`) has a `2px solid var(--accent)` focus ring, consistent with the
  existing `.btn`/`.sidebar-btn` rules.

---

## 11. Implementation checklist (for the developer)

- [ ] Add `--whale` / `--whale-soft` tokens to all three `:root` blocks.
- [ ] `Sidebar`: add `dockerEnabled` prop + Docker item; add `desc` to all
      items; add `.tip` flyout to every button; drop native `title`.
- [ ] `App.jsx`: extend `section` union with `"docker"`; render `DockerView`
      when selected; pass `dockerEnabled = health.features?.docker`.
- [ ] New components: `DockerView`, `DockerGauges`, `StackCard`,
      `ContainerRow`, `ResourceMeter`, `ContainerLogs`.
- [ ] `api.js`: `getDockerOverview()`, `getContainerLogs(name, opts)`.
- [ ] `config.js` + entrypoint: `DOCKER_REFRESH_SECONDS` (default 5).
- [ ] Append the NEW CSS blocks above to `styles.css` (grouped, commented, in
      the same order/section style as the existing file).
- [ ] Reuse `Gauge`, `GaugeCard`, `Header`, `fmtBytes`, `fmtRate`, `fmtClock`,
      `usePolling`, `.search`/`.input`/`.seg`/`.btn`/`.live-dot` — do not
      reimplement.
- [ ] No new npm/pnpm dependency. All icons hand-drawn stroke SVG.
</content>
</invoke>
