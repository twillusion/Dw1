# Digimon World 1 Battle Simulator — Claude Context

## Project Summary
Real-time browser-based battle simulator reverse-engineered from Digimon World 1 (PS1).
Flask + Flask-SocketIO backend; vanilla JS frontend; WebSocket sync at 30 ticks/sec.

## File Map

| File | Purpose |
|------|---------|
| `app.py` | Flask server, WebSocket event handlers, per-client BattleEngine instances |
| `engine/data.py` | Digimon stats, techniques, type chart, constants |
| `engine/formulas.py` | Damage/hit/MP calc; cites ROM offsets (e.g. 0x5BEB8) |
| `engine/fighter.py` | `FighterData` / `Fighter` class |
| `engine/battle.py` | 30-tick/sec battle loop, `Projectile` dataclass, AI, status effects |
| `static/index.html` | UI markup |
| `static/style.css` | All styling (~19 KB) |
| `static/battle.js` | Client: Socket.IO, DOM updates, CSS-3D arena rendering |

## Architecture

- Each WebSocket client → isolated `BattleEngine` instance in a background thread
- Engine emits state snapshots every tick; client applies them to DOM
- No canvas — arena is pure CSS 3D (`perspective` + `rotateX` on a ground plane)
- WebSocket events: `connect`, `disconnect`, `start_battle`, `player_command`, `player_technique`, `finisher_result`, `stop_battle`
- REST: `GET /api/digimon`, `GET /api/techniques`

## Coordinate System

```
pos_z = 0   → player side (near camera, screen bottom)
pos_z = 100 → opponent side (far, screen top)
pos_x = 0   → center; ±60 = field edges; boundary lines at ±55
```

## CSS 3D Arena — Current Parameters (as of last fix)

Ground plane in `#arena`:
- `perspective: 500px`
- `height: 70%` on the ground plane
- `rotateX(60deg)`

Coordinate mapping in `battle.js → setGroundPos()`:
```js
topPct  = 5 + (1 - pos_z / 100) * 85   // far(100)→5%, near(0)→90%
leftPct = 50 + (pos_x / 110) * 15      // ±55 → ±7.5% from center
```

Boundary divs: gold vertical lines at `left: 42.5%` and `57.5%`; horizontal back line at `top: 5%`.

### Why these numbers (last crash fix)

Original values (`perspective: 420px`, `height: 300%`, `rotateX(68°)`) caused sprites
to disappear entirely — the near edge was behind the camera (z_3d > perspective).

Fix: pushed camera back (500px), shrank plane (70%), shallowed angle (60°).
Constraint: `z_3d` of any visible point must stay < `perspective`. At 70% height + 60°
the near-edge z_3d ≈ 120px — well within 500px.

**Do not change these three values independently** — they are coupled. If you need to
adjust the 3D feel, change all three together and verify sprites remain visible.

## Game Mechanics (key formulas)

```
damage = (offense − defense + power) × typeFactor / 17 × rand(90–110%)
```

Type chart, status probabilities, and MP costs are in `engine/data.py`.
Finisher: button-mash mechanic, damage in `formulas.py → calc_finisher_damage()`.

## Known / In-Progress

- Sprite assets are emoji-based (no pixel art)
- WIDE delayed-hit system adds warning overlay (`#wide-warning-overlay`)
- AI movement: approach/retreat based on range vs `SHORT_RANGE_THRESHOLD`

## Session Hygiene (read before starting work)

1. Run `/compact` after each completed feature/fix to prevent context overflow.
2. Scope requests narrowly — name the file and function you want changed.
3. Update this file when architecture or key parameters change.
4. Keep a `TODO.md` for in-progress work that must survive session restarts.
