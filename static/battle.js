/**
 * Digimon World 1 Battle Simulator — Browser Client
 *
 * Connects to Flask-SocketIO backend and renders real-time battle state.
 * Battle engine runs server-side at 30 ticks/sec; events are pushed here.
 */

'use strict';

// -------------------------------------------------------------------------
// Socket connection
// -------------------------------------------------------------------------
const socket = io({ transports: ['websocket'] });

// -------------------------------------------------------------------------
// State
// -------------------------------------------------------------------------
let digimonData = {};        // loaded from /api/digimon
let playerChoice = null;
let opponentChoice = null;
let currentPlayerState = null;
let currentOpponentState = null;
let battleActive = false;

// Finisher state
let finisherInterval = null;
let finisherMashCount = 0;
let finisherTimeLeft = 3;
const FINISHER_DURATION = 3;       // seconds
const FINISHER_MAX_PRESSES = 60;   // 60 presses = 100% bar

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

  commandButtons:   document.getElementById('command-buttons'),
  techniqueButtons: document.getElementById('technique-buttons'),
  battleLog:        document.getElementById('battle-log'),

  finisherOverlay:  document.getElementById('finisher-overlay'),
  finisherMoveName: document.getElementById('finisher-move-name'),
  finisherMashBar:  document.getElementById('finisher-mash-bar'),
  finisherTimer:    document.getElementById('finisher-timer'),
  mashBtn:          document.getElementById('mash-btn'),

  endOverlay:    document.getElementById('end-overlay'),
  endTitle:      document.getElementById('end-title'),
  endSubtitle:   document.getElementById('end-subtitle'),
};

// -------------------------------------------------------------------------
// Initialisation
// -------------------------------------------------------------------------

async function init() {
  const resp = await fetch('/api/digimon');
  digimonData = await resp.json();
  buildSelectors();
  bindEvents();
  showScreen('selection');
}

function buildSelectors() {
  const names = Object.keys(digimonData).sort();
  [el.playerSelect, el.opponentSelect].forEach((sel, idx) => {
    names.forEach(name => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = `${digimonData[name].emoji}  ${name}  [${digimonData[name].stage}]`;
      sel.appendChild(opt);
    });
    // Default selections
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

  // Mash button: keyboard support too
  el.mashBtn.addEventListener('click', handleMash);
  document.addEventListener('keydown', e => {
    if (el.finisherOverlay.style.display !== 'none') {
      handleMash();
    }
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
  showScreen('battle');
  battleActive = true;

  socket.emit('start_battle', {
    player: playerChoice,
    opponent: opponentChoice,
  });
}

function goToSelection() {
  socket.emit('stop_battle');
  battleActive = false;
  hideFinisherOverlay();
  el.endOverlay.style.display = 'none';
  showScreen('selection');
}

function rematch() {
  el.endOverlay.style.display = 'none';
  el.battleLog.innerHTML = '';
  battleActive = true;
  socket.emit('start_battle', {
    player: playerChoice,
    opponent: opponentChoice,
  });
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
  currentPlayerState   = data.player;
  currentOpponentState = data.opponent;
  updateHUD(data.player, data.opponent);
});

socket.on('battle_event', entry => {
  if (!battleActive) return;
  addLogEntry(entry);

  // Animate sprites on attacks
  if (entry.type === 'attack' || entry.type === 'finisher_hit') {
    const isPlayerAttacking = entry.message.startsWith(playerChoice);
    if (isPlayerAttacking) {
      flashSprite(el.plSprite, 'attacking');
      flashSprite(el.oppSprite, 'hurt');
    } else {
      flashSprite(el.oppSprite, 'attacking');
      flashSprite(el.plSprite, 'hurt');
    }
    if (entry.damage > 0) {
      const targetEl = isPlayerAttacking ? el.oppSprite : el.plSprite;
      spawnDmgFloat(targetEl, entry.damage);
    }
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
  // Opponent
  el.oppEmoji.textContent = opponent.emoji;
  el.oppName.textContent  = opponent.name;
  el.oppStage.textContent = `[${opponent.stage}]`;
  el.oppSprite.textContent = opponent.emoji;
  el.oppSprite.title = opponent.name;

  // Player
  el.plEmoji.textContent  = player.emoji;
  el.plName.textContent   = player.name;
  el.plStage.textContent  = `[${player.stage}]`;
  el.plSprite.textContent = player.emoji;
  el.plSprite.title = player.name;

  buildCommandButtons(player);
}

function updateHUD(player, opponent) {
  updateFighterBars(
    opponent,
    el.oppHpBar, el.oppHpText,
    el.oppMpBar, el.oppMpText,
    el.oppSpdBar, el.oppFinBar, el.oppStatuses,
  );
  updateFighterBars(
    player,
    el.plHpBar, el.plHpText,
    el.plMpBar, el.plMpText,
    el.plSpdBar, el.plFinBar, el.plStatuses,
  );

  // Highlight finisher bar when ready
  el.plFinBar.style.boxShadow = player.finisher_ready
    ? '0 0 8px #f39c12' : 'none';
  el.oppFinBar.style.boxShadow = opponent.finisher_ready
    ? '0 0 8px #e74c3c' : 'none';

  // Update command buttons active state
  document.querySelectorAll('.cmd-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.cmd === player.command);
  });
}

function updateFighterBars(
  fighter,
  hpBar, hpText,
  mpBar, mpText,
  spdBar, finBar, statusEl,
) {
  const hpPct = Math.max(0, Math.min(100, fighter.hp_pct * 100));
  const mpPct = Math.max(0, Math.min(100, fighter.mp_pct * 100));

  hpBar.style.width = hpPct + '%';
  mpBar.style.width = (mpPct) + '%';
  spdBar.style.width = (fighter.speed_pct * 100) + '%';
  finBar.style.width = (fighter.finisher_pct * 100) + '%';

  hpText.textContent = `${fighter.current_hp}/${fighter.max_hp}`;
  mpText.textContent = `${fighter.current_mp}/${fighter.max_mp}`;

  // HP bar colour
  hpBar.classList.remove('mid', 'low');
  if (hpPct <= 25) hpBar.classList.add('low');
  else if (hpPct <= 50) hpBar.classList.add('mid');

  // Status badges
  statusEl.innerHTML = (fighter.statuses || []).map(s =>
    `<span class="status-badge status-${s}">${s}</span>`
  ).join('');
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

  // Technique buttons (shown when Manual is selected)
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
  attack:      null,   // uses entry.color
  miss:        '#6a6a8a',
  status:      '#9b59b6',
  finisher:    '#f39c12',
  finisher_hit:'#f39c12',
  command:     '#3498db',
  info:        '#606080',
  end:         '#e74c3c',
};

function addLogEntry(entry) {
  const div = document.createElement('div');
  div.className = 'log-entry';
  const color = entry.color || LOG_TYPE_COLORS[entry.type] || '#c8c8e0';
  div.style.color = color;
  const timeStr = formatTick(entry.tick);
  div.textContent = `[${timeStr}] ${entry.message}`;
  el.battleLog.appendChild(div);

  // Keep only last 80 entries in DOM
  while (el.battleLog.children.length > 80) {
    el.battleLog.removeChild(el.battleLog.firstChild);
  }
  el.battleLog.scrollTop = el.battleLog.scrollHeight;
}

function formatTick(tick) {
  const secs = (tick / 30).toFixed(1);
  return secs + 's';
}

// -------------------------------------------------------------------------
// Sprite animations
// -------------------------------------------------------------------------

function flashSprite(spriteEl, className) {
  spriteEl.classList.remove('attacking', 'hurt');
  void spriteEl.offsetWidth; // force reflow
  spriteEl.classList.add(className);
  setTimeout(() => spriteEl.classList.remove(className), 300);
}

function spawnDmgFloat(targetEl, damage) {
  const float = document.createElement('div');
  float.className = 'dmg-float' + (damage >= 200 ? ' big' : '');
  float.textContent = damage;

  const rect = targetEl.getBoundingClientRect();
  float.style.left = (rect.left + rect.width / 2 + (Math.random() * 30 - 15)) + 'px';
  float.style.top  = (rect.top  - 10) + 'px';
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
  const pct = (finisherMashCount / FINISHER_MAX_PRESSES) * 100;
  el.finisherMashBar.style.width = pct + '%';

  // Auto-submit if bar is full
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
    el.endSubtitle.textContent = `${winner} wins the battle!`;
  } else {
    el.endTitle.textContent = '💀 DEFEATED';
    el.endTitle.style.color = '#e74c3c';
    el.endSubtitle.textContent = `${winner} wins the battle!`;
  }
  el.endOverlay.style.display = 'flex';
}

// -------------------------------------------------------------------------
// Screen switching
// -------------------------------------------------------------------------

function showScreen(name) {
  Object.entries(screens).forEach(([key, el]) => {
    el.classList.toggle('active', key === name);
  });
  document.getElementById('battle-screen').classList.toggle(
    'active', name === 'battle'
  );
}

// -------------------------------------------------------------------------
// Boot
// -------------------------------------------------------------------------

window.addEventListener('DOMContentLoaded', init);
