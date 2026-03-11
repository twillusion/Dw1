# Digimon World 1 — Battle Simulator

A real-time browser-based battle simulator for **Digimon World 1 (PS1)**, with mechanics reverse-engineered from the original game's assembly code via [SydMontague/DW1-Code](https://github.com/SydMontague/DW1-Code).

<!-- Screenshots: drop images into docs/screenshots/ and uncomment below -->
<!--
![Selection screen](docs/screenshots/selection.png)
![Battle in progress](docs/screenshots/battle.png)
-->

---

## Features

- **Authentic battle formulas** sourced directly from `BTL_REL.BIN` disassembly
- **Real-time 3D arena** rendered with Three.js — RTS-style overhead camera, no horizon visible
- **Real-time simulation** at 30 ticks/second with live HP/MP bar updates
- **10 playable Digimon** spanning Rookie through Mega
- **21 techniques** with real Power, MP cost, accuracy, and element data
- **Type effectiveness system** — 7 elements (Fire, Battle, Air, Earth, Ice, Mech, Filth)
- **Status effects** — Poison, Confusion, Paralysis, Stun with frame-accurate timers
- **Finishing move mini-game** — button-mash to boost damage
- **Command menu** — unlocks based on Brains stat (Auto → All-Out → Manual)
- **Damage drain animation** matching the original tiered buffer system
- **Projectile system** — LONG-range techniques spawn travelling projectiles with dodge AI
- **WIDE attacks** — full-field delayed strikes with on-screen warning overlay

---

## Implemented Formulas

| Mechanic | Source |
|---|---|
| `damage = (offense − defense + power) × typeFactor / 17 × rand(90–110)%` | `BTL_REL.BIN 0x5BEB8` |
| Speed buffer fills at `(speed/100)+1` per even tick | `0x0005AF44` |
| Finisher goal = `3000 − speed`, charges 4% of goal per hit | `addFinisherValue.asm 0x5ABC0` |
| Hit chance = `accuracy − (accuracy/2 × speedDiff / 1000)` | `getChanceToHit.asm 0x5BBE4` |
| MP cost = `base × 3`, discounted by Brains at 700/800/900/999 | `getMPCost.asm` |
| Damage drains in chunks of 900/80/6/1 per tick | `Battle.cpp damageTick()` |
| Sick/injured penalty: all stats × 0.8 | `combatInit.asm` |

---

## Getting Started

### Requirements

- Python 3.11+
- pip

### Installation

```bash
git clone <repo-url>
cd Dw1
pip install -r requirements.txt
python app.py
```

Then open **http://localhost:5000** in your browser.

---

## Project Structure

```
Dw1/
├── app.py               # Flask + SocketIO server
├── requirements.txt
├── engine/
│   ├── data.py          # Digimon stats, technique data, type chart
│   ├── formulas.py      # Battle formulas with ASM source citations
│   ├── fighter.py       # FighterData class (mirrors in-game struct)
│   └── battle.py        # 30 ticks/sec real-time battle loop
└── static/
    ├── index.html
    ├── style.css
    └── battle.js        # Three.js arena + Socket.IO client
```

---

## Arena Rendering

The battle arena is rendered with **Three.js r128** (WebGL). A `PerspectiveCamera` is placed at `(0, 210, 120)` looking at the field centre — roughly 60° elevation, which keeps the entire viewport filled with the ground plane and eliminates any sky/horizon.

Engine coordinates (`pos_x`, `pos_z`) map to world space as:
```
world_x = pos_x
world_z = 50 − pos_z   (player near = +50, opponent far = −50)
```

Fighters are `THREE.Sprite` objects with emoji drawn onto a `CanvasTexture`. Directional shadows are flat `PlaneGeometry` meshes offset by a fixed sun vector (`x+10, z+8`). Projectiles use `AdditiveBlending` sprites for a glow effect.

---

## Sources

- **[SydMontague/DW1-Code](https://github.com/SydMontague/DW1-Code)** — primary disassembly of BTL_REL.BIN
- **[SydMontague/DW1-SydPatches](https://github.com/SydMontague/DW1-SydPatches)** — C++ reimplementation (Battle.cpp, dw1.hpp)
- Community stat/technique data from [grindosaur.com](https://grindosaur.com/en/games/digimon-world)
