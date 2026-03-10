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

## Three.js Arena

The CSS-3D approach was abandoned after it proved impossible to eliminate the sky/horizon
using CSS `perspective` + `rotateX`. CSS perspective-origin moves the vanishing point but
cannot position the camera above the field. Three.js solves this directly.

### Camera
```js
camera.position.set(0, 150, 80);  // high in sky, behind player side
camera.lookAt(0, 0, 0);           // look at field center
// PerspectiveCamera fov=45°, near=0.1, far=1000
```
At this position the camera elevation from horizontal ≈ 62°. The frustum top edge hits
world Z ≈ −100, well past the far boundary (Z=−50) — no horizon visible.

### Coordinate Mapping (`battle.js → engineToWorld`)
```js
world_x = pos_x          // engine ±60 → world ±60
world_z = 50 - pos_z     // engine 0 (near) → world +50; engine 100 (far) → world -50
```

### Scene Objects
- Ground: `PlaneGeometry(140, 120)` dark green, + lighter strip on near half
- Grid: `LineSegments`, spacing 10 world units, opacity 0.20
- Boundary: gold `LineSegments` at world x=±55 and z=−50
- Fighters: `THREE.Sprite` with `CanvasTexture` (emoji drawn at 90px serif)
- Shadows: flat `PlaneGeometry` at y=0.05
- Projectiles: `THREE.Sprite` with radial gradient CanvasTexture, `AdditiveBlending`

### Sprite Animation (render loop)
- `winding_up`: scale pulse `BASE_SCALE * (1 + 0.09 * sin(renderTime * π * 5))`
- `attacking`: `material.color.setRGB(1.7, 1.7, 1.7)` — brightness boost for 300ms
- `hurt`: white flash for 300ms
- Managed via `fighters.player/opponent.flashClass` + `flashUntil` timestamp

### CDN
```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
```
r128 = last version with plain `<script>` global `THREE`. No build step.

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
