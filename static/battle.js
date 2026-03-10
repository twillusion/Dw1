/**
 * Digimon World 1 Battle Simulator — Browser Client
 *
 * Connects to Flask-SocketIO backend and renders real-time battle state.
 * Battle engine runs server-side at 30 ticks/sec; events are pushed here.
 *
 * Coordinate system (matches engine):
 *   pos_z = 0  → player side (near camera, bottom of screen)
 *   pos_z = 100 → opponent side (far, top of screen)
 *   pos_x = 0  → centre; -60 left, +60 right
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

// Cached projectile state for canvas drawing
let lastProjectiles = [];
let lastDelayedHits = [];

// WIDE warning animation handle
let wideWarningTimeout = null;

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
  oppSprite:      document.getElementById('opp-sprite'),
  oppSpriteEmoji: document.getElementById('opp-sprite-emoji'),

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
  plSprite:       document.getElementById('player-sprite'),
  plSpriteEmoji:  document.getElementById('pl-sprite-emoji'),

  arena:            document.getElementById('arena'),
  groundCanvas:     document.getElementById('ground-canvas'),
  projectileCanvas: document.getElementById('projectile-canvas'),

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

// Canvas contexts
let groundCtx = null;
let projCtx   = null;

// -------------------------------------------------------------------------
// Perspective field → screen coordinate mapping
// -------------------------------------------------------------------------
// The arena is a plain div. We map field coordinates to absolute pixel
// positions inside it, creating the illusion of a 3D perspective view.
//
// pos_z=0   → bottom of arena (near camera)  → screenY = arenaH * 0.88
// pos_z=100 → top of arena   (far, horizon)  → screenY = arenaH * 0.15
// Scale shrinks linearly with z (objects far away appear smaller).

function fieldToScreen(pos_x, pos_z) {
  const arenaRect = el.arena.getBoundingClientRect();
  const W = arenaRect.width  || el.arena.offsetWidth  || 400;
  const H = arenaRect.height || el.arena.offsetHeight || 180;

  const t = pos_z / 100;             // 0 (near) → 1 (far)
  const screenX = W * (0.5 + pos_x / 140);
  const screenY = H * (0.88 - t * 0.73);  // near at 88%, far at 15%

  // Perspective scale: 1.0 at bottom, 0.45 at horizon
  const scale = 1.0 - t * 0.55;

  return { x: screenX, y: screenY, scale };
}

// -------------------------------------------------------------------------
// Ground grid (perspective)
// Drawn once; redrawn on window resize.
// -------------------------------------------------------------------------
function drawGroundGrid() {
  const canvas = el.groundCanvas;
  const W = canvas.width  = canvas.offsetWidth;
  const H = canvas.height = canvas.offsetHeight;
  const ctx = groundCtx;
  ctx.clearRect(0, 0, W, H);

  // Vanishing point at top-centre
  const vx = W / 2;
  const vy = H * 0.15;

  // Horizon line y (far edge of field)
  const horizonY = H * 0.15;
  // Near edge y
  const nearY = H * 0.90;

  // Number of lateral and depth grid lines
  const lateralLines = 9;   // vertical lines converging to VP
  const depthLines   = 7;   // horizontal lines across the field

  ctx.strokeStyle = '#1e1e30';
  ctx.lineWidth = 1;

  // Lateral lines (converge at vanishing point)
  for (let i = 0; i <= lateralLines; i++) {
    const t = i / lateralLines;
    const nearX = W * t;
    ctx.beginPath();
    ctx.moveTo(vx, vy);
    ctx.lineTo(nearX, nearY);
    ctx.stroke();
  }

  // Depth lines (horizontal, spaced with perspective)
  for (let i = 0; i <= depthLines; i++) {
    const t = i / depthLines;
    // Perspective-correct y position
    const y = horizonY + (nearY - horizonY) * (t * t * 0.6 + t * 0.4);
    // Width at this depth
    const widthRatio = 0.05 + t * 0.95;
    const x0 = vx - (W / 2) * widthRatio;
    const x1 = vx + (W / 2) * widthRatio;
    ctx.beginPath();
    ctx.moveTo(x0, y);
    ctx.lineTo(x1, y);
    ctx.stroke();
  }

  // Subtle glow at horizon
  const grad = ctx.createLinearGradient(0, horizonY - 4, 0, horizonY + 4);
  grad.addColorStop(0, 'transparent');
  grad.addColorStop(0.5, '#2a2a5544');
  grad.addColorStop(1, 'transparent');
  ctx.fillStyle = grad;
  ctx.fillRect(0, horizonY - 4, W, 8);
}

// -------------------------------------------------------------------------
// Projectile canvas rendering
// -------------------------------------------------------------------------
const PROJ_COLORS = {
  FIRE:   '#e74c3c',
  BATTLE: '#95a5a6',
  AIR:    '#1abc9c',
  EARTH:  '#8e6a00',
  ICE:    '#74b9ff',
  MECH:   '#b2bec3',
  FILTH:  '#a29bfe',
};

function drawProjectiles() {
  const canvas = el.projectileCanvas;
  const W = canvas.width  = canvas.offsetWidth;
  const H = canvas.height = canvas.offsetHeight;
  const ctx = projCtx;
  ctx.clearRect(0, 0, W, H);

  for (const p of lastProjectiles) {
    const { x, y, scale } = fieldToScreen(p.pos_x, p.pos_z);
    const radius = Math.max(4, 9 * scale);

    // Determine color from technique type if available
    const tech = digimonData.__techs && digimonData.__techs[p.tech_name];
    const col = tech ? (PROJ_COLORS[tech.type] || '#fff') : '#f39c12';

    // Glow
    const grd = ctx.createRadialGradient(x, y, 0, x, y, radius * 2.5);
    grd.addColorStop(0, col + 'cc');
    grd.addColorStop(1, col + '00');
    ctx.fillStyle = grd;
    ctx.beginPath();
    ctx.arc(x, y, radius * 2.5, 0, Math.PI * 2);
    ctx.fill();

    // Core
    ctx.fillStyle = col;
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
  }

  // WIDE move warning: pulsing ring at defender position
  for (const dh of lastDelayedHits) {
    // Warn at centre of arena since WIDE hits everywhere
    const { x, y } = fieldToScreen(0, 50);
    const alpha = 0.3 + 0.3 * Math.sin(Date.now() / 150);
    const maxR = Math.min(W, H) * 0.4;
    const grd = ctx.createRadialGradient(x, y, 0, x, y, maxR);
    grd.addColorStop(0, `rgba(231,76,60,0)`);
    grd.addColorStop(0.6, `rgba(231,76,60,${alpha * 0.3})`);
    grd.addColorStop(1, `rgba(231,76,60,0)`);
    ctx.fillStyle = grd;
    ctx.fillRect(0, 0, W, H);

    // Countdown text
    const secsLeft = (dh.ticks_remaining / 30).toFixed(1);
    ctx.font = 'bold 11px "Courier New"';
    ctx.fillStyle = `rgba(231,76,60,${0.6 + alpha})`;
    ctx.textAlign = 'center';
    ctx.fillText(`${dh.tech_name} in ${secsLeft}s`, x, y - 20);
  }
}

// Continuously re-render projectile canvas (for smooth animation)
function renderLoop() {
  if (battleActive) drawProjectiles();
  requestAnimationFrame(renderLoop);
}

// -------------------------------------------------------------------------
// Initialisation
// -------------------------------------------------------------------------
async function init() {
  const resp = await fetch('/api/digimon');
  digimonData = await resp.json();

  // Pre-fetch technique data for projectile colours
  const techResp = await fetch('/api/techniques');
  digimonData.__techs = await techResp.json();

  buildSelectors();
  bindEvents();

  groundCtx = el.groundCanvas.getContext('2d');
  projCtx   = el.projectileCanvas.getContext('2d');

  window.addEventListener('resize', () => {
    if (battleActive) drawGroundGrid();
  });

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

  // Draw ground grid once arena is visible
  requestAnimationFrame(() => {
    drawGroundGrid();
  });

  socket.emit('start_battle', { player: playerChoice, opponent: opponentChoice });
}

function goToSelection() {
  socket.emit('stop_battle');
  battleActive = false;
  hideFinisherOverlay();
  el.endOverlay.style.display = 'none';
  el.arena.classList.remove('wide-warning');
  showScreen('selection');
}

function rematch() {
  el.endOverlay.style.display = 'none';
  el.battleLog.innerHTML = '';
  lastProjectiles = [];
  lastDelayedHits = [];
  battleActive = true;
  drawGroundGrid();
  socket.emit('start_battle', { player: playerChoice, opponent: opponentChoice });
}

// -------------------------------------------------------------------------
// Socket events
// -------------------------------------------------------------------------
socket.on('connect', () => console.log('[WS] Connected'));
socket.on('disconnect', () => console.log('[WS] Disconnected'));

socket.on('battle_started', data => {
  initHUD(data.player, data.opponent);
});

socket.on('battle_state', data => {
  if (!battleActive) return;
  updateHUD(data.player, data.opponent);
  updateSpritePositions(data.player, data.opponent);
  lastProjectiles = data.projectiles || [];
  lastDelayedHits = data.delayed_hits || [];

  // WIDE warning visual
  if (lastDelayedHits.length > 0) {
    el.arena.classList.add('wide-warning');
  } else {
    el.arena.classList.remove('wide-warning');
  }
});

socket.on('battle_event', entry => {
  if (!battleActive) return;
  addLogEntry(entry);

  if (entry.type === 'attack' || entry.type === 'finisher_hit' || entry.type === 'projectile_hit') {
    const isPlayerAttacking = entry.message.startsWith(playerChoice);
    if (entry.type === 'projectile_hit' || entry.type === 'attack') {
      flashSprite(isPlayerAttacking ? el.oppSprite : el.plSprite, 'hurt');
    }
    if (entry.damage > 0) {
      spawnDmgFloat(isPlayerAttacking ? el.oppSprite : el.plSprite, entry.damage);
    }
  }

  if (entry.type === 'attack' && !entry.message.includes('incoming')) {
    const isPlayer = entry.message.startsWith(playerChoice);
    flashSprite(isPlayer ? el.plSprite : el.oppSprite, 'attacking');
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
// Sprite positioning
// -------------------------------------------------------------------------
function updateSpritePositions(player, opponent) {
  positionSprite(el.plSprite, player.pos_x, player.pos_z);
  positionSprite(el.oppSprite, opponent.pos_x, opponent.pos_z);
}

function positionSprite(spriteEl, pos_x, pos_z) {
  const { x, y, scale } = fieldToScreen(pos_x, pos_z);
  const size = Math.round(52 * scale);
  spriteEl.style.left  = (x - size / 2) + 'px';
  spriteEl.style.top   = (y - size) + 'px';
  spriteEl.style.transform = `scale(${scale.toFixed(3)})`;
  spriteEl.style.transformOrigin = 'bottom center';
}

// -------------------------------------------------------------------------
// HUD updates
// -------------------------------------------------------------------------
function initHUD(player, opponent) {
  el.oppEmoji.textContent = opponent.emoji;
  el.oppName.textContent  = opponent.name;
  el.oppStage.textContent = `[${opponent.stage}]`;
  el.oppSpriteEmoji.textContent = opponent.emoji;

  el.plEmoji.textContent  = player.emoji;
  el.plName.textContent   = player.name;
  el.plStage.textContent  = `[${player.stage}]`;
  el.plSpriteEmoji.textContent = player.emoji;

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
// Sprite animations
// -------------------------------------------------------------------------
function flashSprite(spriteEl, className) {
  spriteEl.classList.remove('attacking', 'hurt');
  void spriteEl.offsetWidth;
  spriteEl.classList.add(className);
  setTimeout(() => spriteEl.classList.remove(className), 300);
}

function spawnDmgFloat(targetEl, damage) {
  const float = document.createElement('div');
  float.className = 'dmg-float' + (damage >= 200 ? ' big' : '');
  float.textContent = damage;
  const rect = targetEl.getBoundingClientRect();
  float.style.left = (rect.left + rect.width / 2 + (Math.random() * 30 - 15)) + 'px';
  float.style.top  = (rect.top - 10) + 'px';
  float.style.position = 'fixed';
  document.body.appendChild(float);
  setTimeout(() => float.remove(), 1200);
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
