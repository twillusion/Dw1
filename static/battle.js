/**
 * Digimon World 1 Battle Simulator — Browser Client
 *
 * Connects to Flask-SocketIO backend and renders real-time battle state.
 * Battle engine runs server-side at 30 ticks/sec; events are pushed here.
 * Arena is rendered with Three.js (WebGL); all other UI is HTML.
 *
 * Coordinate system (matches engine):
 *   pos_z = 0   → player side (near camera, screen bottom)
 *   pos_z = 100 → opponent side (far, screen top)
 *   pos_x = 0   → centre; -60 left, +60 right
 *
 * World space mapping:
 *   world_x = pos_x          (±60 → ±60 world units)
 *   world_z = 50 - pos_z     (0→+50 near, 100→-50 far)
 */

'use strict';

// -------------------------------------------------------------------------
// Socket connection
// -------------------------------------------------------------------------
const socket = io({ transports: ['websocket'] });

// -------------------------------------------------------------------------
// State
// -------------------------------------------------------------------------
let digimonData = {};
let playerChoice = null;
let opponentChoice = null;
let battleActive = false;

// Finisher state
let finisherInterval = null;
let finisherMashCount = 0;
let finisherTimeLeft = 3;
const FINISHER_DURATION = 3;
const FINISHER_MAX_PRESSES = 60;

// Cached battle state from last server tick
let lastProjectiles = [];
let lastDelayedHits = [];

// -------------------------------------------------------------------------
// DOM refs
// -------------------------------------------------------------------------
const screens = {
  selection: document.getElementById('selection-screen'),
  battle:    document.getElementById('battle-screen'),
};

const el = {
  playerSelect:   document.getElementById('player-select'),
  opponentSelect: document.getElementById('opponent-select'),
  playerPreview:  document.getElementById('player-preview'),
  oppPreview:     document.getElementById('opponent-preview'),
  startBtn:       document.getElementById('start-btn'),
  selectError:    document.getElementById('select-error'),

  backBtn:        document.getElementById('back-btn'),
  rematchBtn:     document.getElementById('rematch-btn'),
  endBackBtn:     document.getElementById('end-back-btn'),

  // Opponent HUD
  oppEmoji:       document.getElementById('opp-emoji'),
  oppName:        document.getElementById('opp-name'),
  oppStage:       document.getElementById('opp-stage'),
  oppStatuses:    document.getElementById('opp-statuses'),
  oppHpBar:       document.getElementById('opp-hp-bar'),
  oppHpText:      document.getElementById('opp-hp-text'),
  oppMpBar:       document.getElementById('opp-mp-bar'),
  oppMpText:      document.getElementById('opp-mp-text'),
  oppSpdBar:      document.getElementById('opp-spd-bar'),
  oppFinBar:      document.getElementById('opp-fin-bar'),

  // Player HUD
  plEmoji:        document.getElementById('pl-emoji'),
  plName:         document.getElementById('pl-name'),
  plStage:        document.getElementById('pl-stage'),
  plStatuses:     document.getElementById('pl-statuses'),
  plHpBar:        document.getElementById('pl-hp-bar'),
  plHpText:       document.getElementById('pl-hp-text'),
  plMpBar:        document.getElementById('pl-mp-bar'),
  plMpText:       document.getElementById('pl-mp-text'),
  plSpdBar:       document.getElementById('pl-spd-bar'),
  plFinBar:       document.getElementById('pl-fin-bar'),

  arena:            document.getElementById('arena'),
  arenaCanvas:      document.getElementById('arena-canvas'),
  wideWarning:      document.getElementById('wide-warning-overlay'),

  commandButtons:   document.getElementById('command-buttons'),
  techniqueButtons: document.getElementById('technique-buttons'),
  battleLog:        document.getElementById('battle-log'),

  finisherOverlay:  document.getElementById('finisher-overlay'),
  finisherMoveName: document.getElementById('finisher-move-name'),
  finisherMashBar:  document.getElementById('finisher-mash-bar'),
  finisherTimer:    document.getElementById('finisher-timer'),
  mashBtn:          document.getElementById('mash-btn'),

  endOverlay:  document.getElementById('end-overlay'),
  endTitle:    document.getElementById('end-title'),
  endSubtitle: document.getElementById('end-subtitle'),
};

// -------------------------------------------------------------------------
// Three.js — scene globals
// -------------------------------------------------------------------------
let scene, camera, renderer;
let renderTime = 0;
let lastRafTime = 0;

// Per-fighter Three.js objects + animation state
const fighters = {
  player: {
    sprite: null, shadow: null,
    state: 'idle', flashClass: null, flashUntil: 0,
  },
  opponent: {
    sprite: null, shadow: null,
    state: 'idle', flashClass: null, flashUntil: 0,
  },
};

// Projectile sprite pool: id → THREE.Sprite
const projSpritePool = {};

const PROJ_COLORS_HEX = {
  FIRE:   0xe74c3c,
  BATTLE: 0x95a5a6,
  AIR:    0x1abc9c,
  EARTH:  0x8e6a00,
  ICE:    0x74b9ff,
  MECH:   0xb2bec3,
  FILTH:  0xa29bfe,
};

// -------------------------------------------------------------------------
// Coordinate mapping
// -------------------------------------------------------------------------
function engineToWorld(pos_x, pos_z) {
  // pos_z=0 (player near) → world Z=+50; pos_z=100 (opponent far) → world Z=-50
  return { x: pos_x, z: 50 - pos_z };
}

// -------------------------------------------------------------------------
// Three.js initialisation
// -------------------------------------------------------------------------
function initArena() {
  renderer = new THREE.WebGLRenderer({ canvas: el.arenaCanvas, antialias: true });
  renderer.setClearColor(0x0c0c1e, 1);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  scene = new THREE.Scene();

  // RTS camera: high in the sky, angled steeply down — no horizon visible
  camera = new THREE.PerspectiveCamera(45, 1, 0.1, 1000);
  camera.position.set(0, 150, 80);
  camera.lookAt(0, 0, 0);

  // Ground plane (XZ, covers field + margin)
  const gGeo = new THREE.PlaneGeometry(140, 120);
  gGeo.rotateX(-Math.PI / 2);
  scene.add(new THREE.Mesh(gGeo,
    new THREE.MeshBasicMaterial({ color: 0x1a4a0e })));

  // Lighter strip toward player side (visual depth cue)
  const stripGeo = new THREE.PlaneGeometry(140, 60);
  stripGeo.rotateX(-Math.PI / 2);
  const strip = new THREE.Mesh(stripGeo,
    new THREE.MeshBasicMaterial({ color: 0x2e6e1e }));
  strip.position.set(0, 0.01, 25);  // near half of field
  scene.add(strip);

  // Grid lines
  const gridPts = [];
  for (let z = -50; z <= 50; z += 10)
    gridPts.push(-70, 0.02, z,  70, 0.02, z);
  for (let x = -70; x <= 70; x += 10)
    gridPts.push(x, 0.02, -50,  x, 0.02, 50);
  const gridGeo = new THREE.BufferGeometry();
  gridGeo.setAttribute('position', new THREE.Float32BufferAttribute(gridPts, 3));
  scene.add(new THREE.LineSegments(gridGeo,
    new THREE.LineBasicMaterial({ color: 0x000000, opacity: 0.20, transparent: true })));

  // Gold boundary lines: pos_x=±55 → world x=±55; pos_z=100 → world z=-50
  const bPts = [
    -55, 0.05,  50,  -55, 0.05, -50,   // left edge
     55, 0.05,  50,   55, 0.05, -50,   // right edge
    -55, 0.05, -50,   55, 0.05, -50,   // back line
  ];
  const bGeo = new THREE.BufferGeometry();
  bGeo.setAttribute('position', new THREE.Float32BufferAttribute(bPts, 3));
  scene.add(new THREE.LineSegments(bGeo,
    new THREE.LineBasicMaterial({ color: 0xffd732, opacity: 0.65, transparent: true })));

  onResize();
  window.addEventListener('resize', onResize);
}

function onResize() {
  const w = el.arenaCanvas.clientWidth;
  const h = el.arenaCanvas.clientHeight;
  if (w === 0 || h === 0) return;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

// -------------------------------------------------------------------------
// Emoji sprite helpers
// -------------------------------------------------------------------------
function makeEmojiTexture(emoji) {
  const cv = document.createElement('canvas');
  cv.width = cv.height = 128;
  const ctx = cv.getContext('2d');
  ctx.font = '90px serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(emoji, 64, 68);
  const tex = new THREE.CanvasTexture(cv);
  tex.needsUpdate = true;
  return tex;
}

function makeEmojiSprite(emoji) {
  const mat = new THREE.SpriteMaterial({
    map: makeEmojiTexture(emoji),
    transparent: true,
    depthWrite: false,
  });
  const sp = new THREE.Sprite(mat);
  sp.scale.set(20, 20, 1);
  sp.position.y = 10;
  return sp;
}

function makeShadowMesh() {
  const g = new THREE.PlaneGeometry(24, 12);
  g.rotateX(-Math.PI / 2);
  const m = new THREE.Mesh(g, new THREE.MeshBasicMaterial({
    color: 0x000000,
    transparent: true,
    opacity: 0.40,
    depthWrite: false,
  }));
  m.position.y = 0.05;
  return m;
}

// -------------------------------------------------------------------------
// Fighter sprite init (called on battle_started and rematch)
// -------------------------------------------------------------------------
function initFighterSprites(playerData, opponentData) {
  // Clean up previous battle sprites (rematch)
  for (const key of ['player', 'opponent']) {
    const f = fighters[key];
    if (f.sprite) { scene.remove(f.sprite); f.sprite.material.map.dispose(); f.sprite.material.dispose(); }
    if (f.shadow) { scene.remove(f.shadow); f.shadow.material.dispose(); }
    f.state = 'idle'; f.flashClass = null; f.flashUntil = 0;
  }

  fighters.player.sprite  = makeEmojiSprite(playerData.emoji);
  fighters.player.shadow  = makeShadowMesh();
  fighters.opponent.sprite = makeEmojiSprite(opponentData.emoji);
  fighters.opponent.shadow = makeShadowMesh();

  scene.add(fighters.player.sprite,   fighters.player.shadow);
  scene.add(fighters.opponent.sprite, fighters.opponent.shadow);

  // Place at initial positions
  const pw = engineToWorld(playerData.pos_x,   playerData.pos_z);
  const ow = engineToWorld(opponentData.pos_x, opponentData.pos_z);
  fighters.player.sprite.position.set(pw.x, 10, pw.z);
  fighters.player.shadow.position.set(pw.x, 0.05, pw.z);
  fighters.opponent.sprite.position.set(ow.x, 10, ow.z);
  fighters.opponent.shadow.position.set(ow.x, 0.05, ow.z);
}

// -------------------------------------------------------------------------
// Sprite position update (called each battle_state tick)
// -------------------------------------------------------------------------
function updateSpritePositions(player, opponent) {
  if (!fighters.player.sprite) return;

  const pw = engineToWorld(player.pos_x, player.pos_z);
  fighters.player.sprite.position.set(pw.x, 10, pw.z);
  fighters.player.shadow.position.set(pw.x, 0.05, pw.z);
  fighters.player.state = player.state;

  const ow = engineToWorld(opponent.pos_x, opponent.pos_z);
  fighters.opponent.sprite.position.set(ow.x, 10, ow.z);
  fighters.opponent.shadow.position.set(ow.x, 0.05, ow.z);
  fighters.opponent.state = opponent.state;
}

// -------------------------------------------------------------------------
// Fighter flash (replaces flashSprite)
// -------------------------------------------------------------------------
function flashFighter(key, type) {
  fighters[key].flashClass  = type;
  fighters[key].flashUntil  = performance.now() + 300;
}

// -------------------------------------------------------------------------
// Per-frame fighter animation
// -------------------------------------------------------------------------
const WINDUP_FREQ = Math.PI * 5;  // ~2.5 Hz pulse
const BASE_SCALE  = 20;

function animateFighterState(fighter) {
  if (!fighter.sprite) return;
  const sp  = fighter.sprite;
  const now = performance.now();

  if (fighter.flashClass && now < fighter.flashUntil) {
    if (fighter.flashClass === 'hurt') {
      sp.material.color.set(0xffffff);  // white flash
      const t = (fighter.flashUntil - now) / 300;
      sp.material.color.setRGB(1, t * 0.3 + 0.7, t * 0.3 + 0.7);
    } else if (fighter.flashClass === 'attacking') {
      sp.material.color.setRGB(1.7, 1.7, 1.7);  // brightness boost
    }
    sp.scale.set(BASE_SCALE, BASE_SCALE, 1);
  } else {
    fighter.flashClass = null;
    sp.material.color.set(0xffffff);

    if (fighter.state === 'winding_up') {
      const s = BASE_SCALE * (1 + 0.09 * Math.sin(renderTime * WINDUP_FREQ));
      sp.scale.set(s, s, 1);
    } else {
      sp.scale.set(BASE_SCALE, BASE_SCALE, 1);
    }
  }
}

// -------------------------------------------------------------------------
// Projectile sprites (replaces updateProjectileDivs)
// -------------------------------------------------------------------------
function hexToRgb255(hex) {
  return `${(hex >> 16) & 0xff},${(hex >> 8) & 0xff},${hex & 0xff}`;
}

function makeProjectileSprite(techType) {
  const color = PROJ_COLORS_HEX[techType] || 0xf39c12;
  const cv = document.createElement('canvas');
  cv.width = cv.height = 64;
  const ctx = cv.getContext('2d');
  const grad = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0,    `rgba(${hexToRgb255(color)},1.0)`);
  grad.addColorStop(0.35, `rgba(${hexToRgb255(color)},0.7)`);
  grad.addColorStop(1,    `rgba(${hexToRgb255(color)},0.0)`);
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 64, 64);
  const mat = new THREE.SpriteMaterial({
    map: new THREE.CanvasTexture(cv),
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  const sp = new THREE.Sprite(mat);
  sp.scale.set(10, 10, 1);
  sp.position.y = 3;
  return sp;
}

function updateProjectiles(projectiles) {
  const alive = new Set(projectiles.map(p => p.id));

  for (const [id, sp] of Object.entries(projSpritePool)) {
    if (!alive.has(+id)) {
      scene.remove(sp);
      sp.material.map.dispose();
      sp.material.dispose();
      delete projSpritePool[id];
    }
  }

  const techs = digimonData.__techs || {};
  for (const p of projectiles) {
    let sp = projSpritePool[p.id];
    if (!sp) {
      const tech = techs[p.tech_name];
      sp = makeProjectileSprite(tech ? tech.type : 'BATTLE');
      scene.add(sp);
      projSpritePool[p.id] = sp;
    }
    const { x, z } = engineToWorld(p.pos_x, p.pos_z);
    sp.position.set(x, 3, z);
  }
}

// -------------------------------------------------------------------------
// Damage float numbers (3D world pos → fixed screen pos)
// -------------------------------------------------------------------------
function spawnDmgFloat(worldPos3, damage) {
  const ndc    = worldPos3.clone().project(camera);
  const canvas = el.arenaCanvas;
  const rect   = canvas.getBoundingClientRect();
  const sx     = (ndc.x *  0.5 + 0.5) * rect.width  + rect.left;
  const sy     = (ndc.y * -0.5 + 0.5) * rect.height + rect.top;

  const float = document.createElement('div');
  float.className = 'dmg-float' + (damage >= 200 ? ' big' : '');
  float.textContent = damage;
  float.style.left     = (sx + (Math.random() * 30 - 15)) + 'px';
  float.style.top      = (sy - 10) + 'px';
  float.style.position = 'fixed';
  document.body.appendChild(float);
  setTimeout(() => float.remove(), 1200);
}

// -------------------------------------------------------------------------
// Render loop
// -------------------------------------------------------------------------
function renderLoop(timestamp) {
  requestAnimationFrame(renderLoop);
  const dt = Math.min((timestamp - lastRafTime) / 1000, 0.1);
  lastRafTime = timestamp;
  renderTime += dt;

  if (battleActive) {
    updateProjectiles(lastProjectiles);
    animateFighterState(fighters.player);
    animateFighterState(fighters.opponent);
    el.wideWarning.classList.toggle('active', lastDelayedHits.length > 0);
  }

  renderer.render(scene, camera);
}

// -------------------------------------------------------------------------
// Initialisation
// -------------------------------------------------------------------------
async function init() {
  const resp = await fetch('/api/digimon');
  digimonData = await resp.json();

  const techResp = await fetch('/api/techniques');
  digimonData.__techs = await techResp.json();

  initArena();
  buildSelectors();
  bindEvents();
  showScreen('selection');
  requestAnimationFrame(renderLoop);
}

function buildSelectors() {
  const names = Object.keys(digimonData).filter(k => k !== '__techs').sort();
  [el.playerSelect, el.opponentSelect].forEach((sel, idx) => {
    names.forEach(name => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = `${digimonData[name].emoji}  ${name}  [${digimonData[name].stage}]`;
      sel.appendChild(opt);
    });
    sel.value = idx === 0 ? 'Greymon' : 'Garurumon';
  });
  updatePreview(el.playerSelect, el.playerPreview);
  updatePreview(el.opponentSelect, el.oppPreview);
}

function updatePreview(selectEl, previewEl) {
  const name = selectEl.value;
  const d = digimonData[name];
  if (!d) return;
  previewEl.innerHTML = `
    <span class="preview-emoji">${d.emoji}</span>
    <div class="preview-name">${name}</div>
    <div class="preview-stage">${d.stage}</div>
    <div style="margin-top:8px">
      <div class="preview-stat"><span>HP</span><span>${d.hp}</span></div>
      <div class="preview-stat"><span>MP</span><span>${d.mp}</span></div>
      <div class="preview-stat"><span>OFF</span><span>${d.offense}</span></div>
      <div class="preview-stat"><span>DEF</span><span>${d.defense}</span></div>
      <div class="preview-stat"><span>SPD</span><span>${d.speed}</span></div>
      <div class="preview-stat"><span>BRN</span><span>${d.brains}</span></div>
    </div>
    <div class="preview-types">
      ${(d.techniques || []).map(t =>
        `<span class="type-${t.type || ''}" style="font-size:9px">${t.name}</span>`
      ).join(' · ')}
    </div>
  `;
}

// -------------------------------------------------------------------------
// Events
// -------------------------------------------------------------------------
function bindEvents() {
  el.playerSelect.addEventListener('change',
    () => updatePreview(el.playerSelect, el.playerPreview));
  el.opponentSelect.addEventListener('change',
    () => updatePreview(el.opponentSelect, el.oppPreview));

  el.startBtn.addEventListener('click', startBattle);
  el.backBtn.addEventListener('click', goToSelection);
  el.rematchBtn.addEventListener('click', rematch);
  el.endBackBtn.addEventListener('click', goToSelection);

  el.mashBtn.addEventListener('click', handleMash);
  document.addEventListener('keydown', () => {
    if (el.finisherOverlay.style.display !== 'none') handleMash();
  });
}

function startBattle() {
  playerChoice   = el.playerSelect.value;
  opponentChoice = el.opponentSelect.value;
  if (playerChoice === opponentChoice) {
    el.selectError.textContent = 'Choose different Digimon!';
    return;
  }
  el.selectError.textContent = '';
  el.battleLog.innerHTML = '';
  lastProjectiles = [];
  lastDelayedHits = [];
  showScreen('battle');
  battleActive = true;
  // Give the layout one frame to resolve canvas dimensions before resizing
  requestAnimationFrame(onResize);
  socket.emit('start_battle', { player: playerChoice, opponent: opponentChoice });
}

function goToSelection() {
  socket.emit('stop_battle');
  battleActive = false;
  updateProjectiles([]);  // clear projectile sprites
  hideFinisherOverlay();
  el.endOverlay.style.display = 'none';
  el.wideWarning.classList.remove('active');
  showScreen('selection');
}

function rematch() {
  el.endOverlay.style.display = 'none';
  el.battleLog.innerHTML = '';
  lastProjectiles = [];
  lastDelayedHits = [];
  battleActive = true;
  socket.emit('start_battle', { player: playerChoice, opponent: opponentChoice });
}

// -------------------------------------------------------------------------
// Socket events
// -------------------------------------------------------------------------
socket.on('connect', () => console.log('[WS] Connected'));
socket.on('disconnect', () => console.log('[WS] Disconnected'));

socket.on('battle_started', data => {
  initHUD(data.player, data.opponent);
  initFighterSprites(data.player, data.opponent);
});

socket.on('battle_state', data => {
  if (!battleActive) return;
  updateHUD(data.player, data.opponent);
  updateSpritePositions(data.player, data.opponent);
  lastProjectiles = data.projectiles || [];
  lastDelayedHits = data.delayed_hits || [];
});

socket.on('battle_event', entry => {
  if (!battleActive) return;
  addLogEntry(entry);

  if (entry.type === 'attack' || entry.type === 'finisher_hit' || entry.type === 'projectile_hit') {
    const isPlayerAttacking = entry.message.startsWith(playerChoice);
    if (entry.type === 'projectile_hit' || entry.type === 'attack') {
      flashFighter(isPlayerAttacking ? 'opponent' : 'player', 'hurt');
    }
    if (entry.damage > 0) {
      const targetKey = isPlayerAttacking ? 'opponent' : 'player';
      const f = fighters[targetKey];
      if (f.sprite) {
        const worldPos = f.sprite.position.clone();
        worldPos.y += 12;
        spawnDmgFloat(worldPos, entry.damage);
      }
    }
  }

  if (entry.type === 'attack' && !entry.message.includes('incoming')) {
    const isPlayer = entry.message.startsWith(playerChoice);
    flashFighter(isPlayer ? 'player' : 'opponent', 'attacking');
  }
});

socket.on('finisher_ready', data => {
  if (!battleActive) return;
  showFinisherOverlay(data.move, data.power);
});

socket.on('battle_end', data => {
  battleActive = false;
  hideFinisherOverlay();
  showEndScreen(data.winner);
});

socket.on('error', data => {
  el.selectError.textContent = data.message || 'An error occurred.';
  showScreen('selection');
});

// -------------------------------------------------------------------------
// HUD updates
// -------------------------------------------------------------------------
function initHUD(player, opponent) {
  el.oppEmoji.textContent = opponent.emoji;
  el.oppName.textContent  = opponent.name;
  el.oppStage.textContent = `[${opponent.stage}]`;

  el.plEmoji.textContent  = player.emoji;
  el.plName.textContent   = player.name;
  el.plStage.textContent  = `[${player.stage}]`;

  buildCommandButtons(player);
}

function updateHUD(player, opponent) {
  updateFighterBars(opponent,
    el.oppHpBar, el.oppHpText, el.oppMpBar, el.oppMpText,
    el.oppSpdBar, el.oppFinBar, el.oppStatuses);
  updateFighterBars(player,
    el.plHpBar, el.plHpText, el.plMpBar, el.plMpText,
    el.plSpdBar, el.plFinBar, el.plStatuses);

  el.plFinBar.style.boxShadow  = player.finisher_ready   ? '0 0 8px #f39c12' : 'none';
  el.oppFinBar.style.boxShadow = opponent.finisher_ready ? '0 0 8px #e74c3c' : 'none';

  document.querySelectorAll('.cmd-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.cmd === player.command);
  });
}

function updateFighterBars(fighter,
  hpBar, hpText, mpBar, mpText, spdBar, finBar, statusEl) {
  const hpPct = Math.max(0, Math.min(100, fighter.hp_pct * 100));
  hpBar.style.width  = hpPct + '%';
  mpBar.style.width  = Math.max(0, Math.min(100, fighter.mp_pct * 100)) + '%';
  spdBar.style.width = (fighter.speed_pct * 100) + '%';
  finBar.style.width = (fighter.finisher_pct * 100) + '%';
  hpText.textContent = `${fighter.current_hp}/${fighter.max_hp}`;
  mpText.textContent = `${fighter.current_mp}/${fighter.max_mp}`;
  hpBar.classList.remove('mid', 'low');
  if (hpPct <= 25) hpBar.classList.add('low');
  else if (hpPct <= 50) hpBar.classList.add('mid');
  statusEl.innerHTML = (fighter.statuses || []).map(s =>
    `<span class="status-badge status-${s}">${s}</span>`).join('');
}

// -------------------------------------------------------------------------
// Command buttons
// -------------------------------------------------------------------------
function buildCommandButtons(player) {
  el.commandButtons.innerHTML = '';
  el.techniqueButtons.innerHTML = '';

  const cmds = player.available_commands || ['Auto'];
  cmds.forEach(cmd => {
    const btn = document.createElement('button');
    btn.className = 'cmd-btn' + (cmd === player.command ? ' active' : '');
    btn.textContent = cmd;
    btn.dataset.cmd = cmd;
    btn.addEventListener('click', () => {
      if (cmd === 'Manual') {
        el.techniqueButtons.style.display =
          el.techniqueButtons.style.display === 'none' ? 'flex' : 'none';
      } else {
        socket.emit('player_command', { command: cmd });
        el.techniqueButtons.style.display = 'none';
      }
    });
    el.commandButtons.appendChild(btn);
  });

  if (digimonData[playerChoice]) {
    const techs = digimonData[playerChoice].techniques || [];
    techs.forEach(tech => {
      const btn = document.createElement('button');
      btn.className = 'tech-btn';
      btn.innerHTML = `
        <span class="type-${tech.type}">${tech.name}</span>
        <span class="tech-cost">${tech.mp_cost}MP</span>
      `;
      btn.title = `${tech.description || ''} | Power: ${tech.power} | Acc: ${tech.accuracy}%`;
      btn.addEventListener('click', () => {
        socket.emit('player_technique', { technique: tech.name });
        el.techniqueButtons.style.display = 'none';
      });
      el.techniqueButtons.appendChild(btn);
    });
  }
}

// -------------------------------------------------------------------------
// Battle log
// -------------------------------------------------------------------------
const LOG_TYPE_COLORS = {
  attack:          null,
  projectile_hit:  '#f39c12',
  projectile_miss: '#6a6a8a',
  wide_warning:    '#e74c3c',
  miss:            '#6a6a8a',
  status:          '#9b59b6',
  finisher:        '#f39c12',
  finisher_hit:    '#f39c12',
  command:         '#3498db',
  info:            '#606080',
  end:             '#e74c3c',
};

function addLogEntry(entry) {
  const div = document.createElement('div');
  div.className = 'log-entry';
  const color = entry.color || LOG_TYPE_COLORS[entry.type] || '#c8c8e0';
  div.style.color = color;
  div.textContent = `[${(entry.tick / 30).toFixed(1)}s] ${entry.message}`;
  el.battleLog.appendChild(div);
  while (el.battleLog.children.length > 80) {
    el.battleLog.removeChild(el.battleLog.firstChild);
  }
  el.battleLog.scrollTop = el.battleLog.scrollHeight;
}

// -------------------------------------------------------------------------
// Finisher mini-game
// -------------------------------------------------------------------------
function showFinisherOverlay(moveName, power) {
  finisherMashCount = 0;
  finisherTimeLeft  = FINISHER_DURATION;
  el.finisherMoveName.textContent = moveName;
  el.finisherMashBar.style.width = '0%';
  el.finisherTimer.textContent   = finisherTimeLeft;
  el.finisherOverlay.style.display = 'flex';
  finisherInterval = setInterval(() => {
    finisherTimeLeft--;
    el.finisherTimer.textContent = finisherTimeLeft;
    if (finisherTimeLeft <= 0) {
      clearInterval(finisherInterval);
      submitFinisher();
    }
  }, 1000);
}

function handleMash() {
  if (el.finisherOverlay.style.display === 'none') return;
  finisherMashCount = Math.min(FINISHER_MAX_PRESSES, finisherMashCount + 1);
  el.finisherMashBar.style.width =
    (finisherMashCount / FINISHER_MAX_PRESSES * 100) + '%';
  if (finisherMashCount >= FINISHER_MAX_PRESSES) {
    clearInterval(finisherInterval);
    submitFinisher();
  }
}

function submitFinisher() {
  const mashScore = Math.round((finisherMashCount / FINISHER_MAX_PRESSES) * 100);
  hideFinisherOverlay();
  socket.emit('finisher_result', { mash_score: mashScore });
}

function hideFinisherOverlay() {
  if (finisherInterval) clearInterval(finisherInterval);
  el.finisherOverlay.style.display = 'none';
}

// -------------------------------------------------------------------------
// Battle end
// -------------------------------------------------------------------------
function showEndScreen(winner) {
  if (winner === playerChoice) {
    el.endTitle.textContent = '🏆 VICTORY!';
    el.endTitle.style.color = '#f39c12';
  } else {
    el.endTitle.textContent = '💀 DEFEATED';
    el.endTitle.style.color = '#e74c3c';
  }
  el.endSubtitle.textContent = `${winner} wins the battle!`;
  el.endOverlay.style.display = 'flex';
}

// -------------------------------------------------------------------------
// Screen switching
// -------------------------------------------------------------------------
function showScreen(name) {
  Object.entries(screens).forEach(([key, screenEl]) => {
    screenEl.classList.toggle('active', key === name);
  });
  document.getElementById('battle-screen').classList.toggle('active', name === 'battle');
}

// -------------------------------------------------------------------------
// Boot
// -------------------------------------------------------------------------
window.addEventListener('DOMContentLoaded', init);
