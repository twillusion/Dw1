"""
Battle engine for Digimon World 1 battle simulator.

Runs a tick-based real-time simulation at 30 ticks/second in a background
thread. Emits structured events via a callback to be forwarded over WebSocket.

Battle flow per tick:
  1. Tick status timers, cooldowns, speed buffers
  2. Apply damage drain from hpDamageBuffer (visual drain animation)
  3. Apply poison HP drain
  4. Check if either fighter can act → choose and execute a technique
  5. Check for battle end (HP <= 0)
  6. Emit state snapshot every tick
"""

import time
import random
import threading
from typing import Callable

from .fighter import Fighter, make_fighter
from .data import TECHNIQUES, DIGIMON, POISON_DRAIN_PER_SEC
from .formulas import (
    calc_damage, calc_hit_chance, calc_mp_cost, roll_hit, roll_status,
    confusion_attacks_self, damage_tick, calc_finisher_damage,
)

TICK_RATE = 30          # ticks per second
TICK_SLEEP = 1 / TICK_RATE


class BattleEngine:
    def __init__(
        self,
        player_name: str,
        opponent_name: str,
        emit_fn: Callable[[str, dict], None],
    ):
        self.player: Fighter = make_fighter(player_name, is_player=True)
        self.opponent: Fighter = make_fighter(opponent_name, is_player=False)
        self.emit = emit_fn

        self.tick_count: int = 0
        self.running: bool = False
        self._thread: threading.Thread | None = None

        self.log: list[dict] = []
        self.battle_over: bool = False
        self.winner: str | None = None

        # Pending finisher: waiting for player mash input
        self._pending_finisher: dict | None = None

        # Lock for thread-safe state access
        self._lock = threading.Lock()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False

    def set_player_command(self, command: str):
        with self._lock:
            if command in self.player.available_commands:
                self.player.command = command
                self._log_event("command", f"{self.player.name} switches to {command} mode.")

    def set_player_technique(self, technique: str):
        """For Manual mode: queue a specific technique."""
        with self._lock:
            if technique in self.player.techniques:
                self.player.command = "Manual"
                self.player._manual_tech = technique  # temporary attribute

    def resolve_finisher(self, mash_score: int):
        """
        Called when the player completes the button-mash mini-game.
        mash_score: 0–100 (number of button presses in the time window)
        """
        with self._lock:
            if self._pending_finisher:
                pf = self._pending_finisher
                self._pending_finisher = None
                self._apply_finisher_damage(
                    attacker=pf["attacker"],
                    defender=pf["defender"],
                    mash_score=mash_score,
                )

    # -----------------------------------------------------------------------
    # Main loop
    # -----------------------------------------------------------------------

    def _loop(self):
        while self.running and not self.battle_over:
            with self._lock:
                self._tick()
            time.sleep(TICK_SLEEP)

        if self.battle_over:
            self.emit("battle_end", {
                "winner": self.winner,
                "log": self.log[-20:],
                "player": self.player.to_dict(),
                "opponent": self.opponent.to_dict(),
            })

    def _tick(self):
        self.tick_count += 1
        t = self.tick_count

        # 1. Tick timers
        for f in (self.player, self.opponent):
            f.tick_speed_buffer(t)
            f.tick_cooldown()
            f.tick_status_timers()

        # 2. Drain HP from damage buffer (visual drain animation)
        for f in (self.player, self.opponent):
            if f.hp_damage_buffer > 0:
                f.hp_damage_buffer, f.current_hp = damage_tick(
                    f.hp_damage_buffer, f.current_hp
                )

        # 3. Poison HP drain (once per second = every TICK_RATE ticks)
        if t % TICK_RATE == 0:
            for f in (self.player, self.opponent):
                if f.is_poisoned:
                    drain = POISON_DRAIN_PER_SEC.get(f.stage, 20)
                    f.current_hp = max(0, f.current_hp - drain)
                    self._log_event(
                        "status",
                        f"{f.name} takes {drain} poison damage! ({f.current_hp}/{f.max_hp} HP)",
                        color="#9b59b6",
                    )

        # 4. Check for battle end
        if self._check_end():
            return

        # 5. Wait if finisher resolution is pending (player must mash)
        if self._pending_finisher:
            self._emit_state()
            return

        # 6. Let each fighter act if able
        for attacker, defender in [
            (self.player, self.opponent),
            (self.opponent, self.player),
        ]:
            if attacker.can_act:
                self._execute_action(attacker, defender)

        # 7. Emit state to browser every tick
        self._emit_state()

    # -----------------------------------------------------------------------
    # Action execution
    # -----------------------------------------------------------------------

    def _execute_action(self, attacker: Fighter, defender: Fighter):
        # Confused? May attack self
        if attacker.is_confused and confusion_attacks_self():
            self._log_event(
                "status",
                f"{attacker.name} is confused and attacks itself!",
                color="#e67e22",
            )
            # Self-damage: use weakest move at half power
            tech_name = min(attacker.techniques, key=lambda t: TECHNIQUES[t]["power"])
            tech = TECHNIQUES[tech_name]
            dmg = calc_damage(
                attacker.effective_offense,
                attacker.effective_defense,
                tech["power"] // 2,
                tech["type"],
                attacker.def_type,
                is_enemy=not attacker.is_player,
            )
            attacker.hp_damage_buffer += dmg
            attacker.reset_speed_buffer()
            return

        # Choose technique
        if hasattr(attacker, "_manual_tech") and attacker._manual_tech:
            tech_name = attacker._manual_tech
            attacker._manual_tech = None
            if tech_name not in attacker.techniques or tech_name not in TECHNIQUES:
                tech_name = attacker.choose_technique()
        else:
            tech_name = attacker.choose_technique()

        if tech_name is None:
            # No MP for any move — basic attack (half weakest power, no cost)
            attacker.reset_speed_buffer()
            self._log_event("info", f"{attacker.name} has no MP left to attack!")
            return

        tech = TECHNIQUES[tech_name]

        # Deduct MP
        mp_cost = calc_mp_cost(tech["mp_cost"], attacker.brains, attacker.is_sick)
        if attacker.current_mp < mp_cost:
            attacker.reset_speed_buffer()
            return

        attacker.current_mp -= mp_cost

        # Check hit
        hit_chance = calc_hit_chance(
            attacker_speed=attacker.speed,
            victim_speed=defender.speed,
            move_accuracy=tech["accuracy"],
        )
        if not roll_hit(hit_chance):
            attacker.reset_speed_buffer()
            self._log_event(
                "miss",
                f"{attacker.name} uses {tech_name}... but misses!",
                color="#95a5a6",
            )
            return

        # Calculate and apply damage
        dmg = calc_damage(
            attacker_offense=attacker.effective_offense,
            defender_defense=defender.effective_defense,
            move_power=tech["power"],
            attacker_type=tech["type"],
            defender_type=defender.def_type,
            mastery_count=attacker.mastery_counts.get(tech_name, 0),
            is_enemy=not attacker.is_player,
        )

        # Type effectiveness label
        type_factor = _type_label(tech["type"], defender.def_type)

        defender.hp_damage_buffer = min(
            9999, defender.hp_damage_buffer + dmg
        )
        attacker.hit_count += 1
        if dmg > 200:
            attacker.heavy_hit_count += 1

        # Mastery tick
        attacker.mastery_counts[tech_name] = min(
            99, attacker.mastery_counts.get(tech_name, 0) + 1
        )

        # Status effect
        status_msg = ""
        if tech["status"] and roll_status(tech["status_chance"]):
            defender.apply_status(tech["status"])
            status_msg = f" {defender.name} is {tech['status'].lower()}ed!"

        self._log_event(
            "attack",
            f"{attacker.name} uses {tech_name}{type_factor} → {dmg} dmg!{status_msg}",
            color=attacker.color,
            damage=dmg,
        )

        # Advance finisher meter
        attacker.advance_finisher()

        # Check if finisher is ready
        if attacker.finisher_ready:
            self._trigger_finisher(attacker, defender)

        attacker.reset_speed_buffer()

    def _trigger_finisher(self, attacker: Fighter, defender: Fighter):
        """Emit finisher event; pause battle until mash resolved."""
        attacker.reset_finisher()
        self._log_event(
            "finisher",
            f"✦ {attacker.name} charges a FINISHING MOVE: {attacker.finisher_name}!",
            color="#f39c12",
        )

        if attacker.is_player:
            # Player must mash — store pending and emit event to browser
            self._pending_finisher = {
                "attacker": attacker,
                "defender": defender,
            }
            self.emit("finisher_ready", {
                "attacker": attacker.name,
                "move": attacker.finisher_name,
                "power": attacker.finisher_power,
            })
        else:
            # Enemy AI: simulate mash score (60–90)
            mash_score = random.randint(60, 90)
            self._apply_finisher_damage(attacker, defender, mash_score)

    def _apply_finisher_damage(
        self, attacker: Fighter, defender: Fighter, mash_score: int
    ):
        dmg = calc_finisher_damage(
            move_power=attacker.finisher_power,
            attacker_type=DIGIMON[attacker.name]["def_type"],
            defender_type=defender.def_type,
            mash_score=mash_score,
        )
        defender.hp_damage_buffer = min(9999, defender.hp_damage_buffer + dmg)
        quality = "PERFECT" if mash_score >= 90 else "GREAT" if mash_score >= 60 else "OK"
        self._log_event(
            "finisher_hit",
            f"⚡ {attacker.name}: {attacker.finisher_name} ({quality})! → {dmg} dmg!",
            color="#f39c12",
            damage=dmg,
        )
        self._emit_state()

    # -----------------------------------------------------------------------
    # Battle end
    # -----------------------------------------------------------------------

    def _check_end(self) -> bool:
        for f, other in [(self.player, self.opponent), (self.opponent, self.player)]:
            # Battle ends when drain brings HP to 0
            if f.current_hp <= 0 and f.hp_damage_buffer == 0:
                self.battle_over = True
                self.running = False
                self.winner = other.name
                self._log_event(
                    "end",
                    f"{f.name} has been defeated! {other.name} wins!",
                    color="#e74c3c",
                )
                return True
        return False

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _log_event(
        self, event_type: str, message: str, color: str = "#ecf0f1", damage: int = 0
    ):
        entry = {
            "tick": self.tick_count,
            "type": event_type,
            "message": message,
            "color": color,
            "damage": damage,
        }
        self.log.append(entry)
        if len(self.log) > 200:
            self.log = self.log[-200:]
        self.emit("battle_event", entry)

    def _emit_state(self):
        self.emit("battle_state", {
            "tick": self.tick_count,
            "player": self.player.to_dict(),
            "opponent": self.opponent.to_dict(),
            "awaiting_finisher": self._pending_finisher is not None and self.player.finisher_ready
            if self._pending_finisher else False,
        })


def _type_label(attack_type: str, defend_type: str) -> str:
    """Returns a short effectiveness label for the battle log."""
    from .data import get_type_factor
    factor = get_type_factor(attack_type, defend_type)
    if factor >= 20:
        return " [SUPER EFFECTIVE]"
    elif factor >= 15:
        return " [effective]"
    elif factor <= 2:
        return " [BARELY EFFECTIVE]"
    elif factor <= 5:
        return " [not very effective]"
    return ""
