"""
Battle engine for Digimon World 1 battle simulator.

Runs a tick-based real-time simulation at 30 ticks/second in a background
thread. Emits structured events via a callback to be forwarded over WebSocket.

Battle flow per tick:
  1. Tick status timers, cooldowns, speed buffers
  2. Move fighters (approach/retreat AI)
  3. Move projectiles; check collisions; despawn expired
  4. Tick delayed-hit timers (WIDE moves)
  5. Apply damage drain from hpDamageBuffer (visual drain animation)
  6. Apply poison HP drain
  7. Check if either fighter can act → choose and execute a technique
  8. Check for battle end (HP <= 0)
  9. Emit state snapshot every tick
"""

import math
import time
import random
import threading
from dataclasses import dataclass, field
from typing import Callable

from .fighter import Fighter, make_fighter
from .data import (
    TECHNIQUES, DIGIMON, POISON_DRAIN_PER_SEC,
    SHORT_RANGE_THRESHOLD, PROJECTILE_SPEED, DODGE_THRESHOLD,
)
from .formulas import (
    calc_damage, calc_hit_chance, calc_mp_cost, roll_hit, roll_status,
    confusion_attacks_self, damage_tick, calc_finisher_damage,
)

TICK_RATE = 30
TICK_SLEEP = 1 / TICK_RATE


# ---------------------------------------------------------------------------
# Projectile
# ---------------------------------------------------------------------------

@dataclass
class Projectile:
    """A traveling attack projectile on the 2.5D field."""
    id: int
    pos_x: float
    pos_z: float
    vel_x: float          # x units per tick
    vel_z: float          # z units per tick (negative = toward player side)
    attacker_name: str    # name of the Fighter that fired it
    defender_name: str
    tech_name: str
    damage: int
    status: str | None
    status_chance: int
    dodgeable: bool
    life: int = 60        # despawn after this many ticks (~2 seconds)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "pos_x": round(self.pos_x, 2),
            "pos_z": round(self.pos_z, 2),
            "tech_name": self.tech_name,
            "dodgeable": self.dodgeable,
        }


# ---------------------------------------------------------------------------
# DelayedHit (WIDE moves)
# ---------------------------------------------------------------------------

@dataclass
class DelayedHit:
    """A queued WIDE-range attack that lands after a fixed delay."""
    id: int
    attacker_name: str
    defender_name: str
    tech_name: str
    damage: int
    status: str | None
    status_chance: int
    ticks_remaining: int

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tech_name": self.tech_name,
            "ticks_remaining": self.ticks_remaining,
            "attacker": self.attacker_name,
        }


# ---------------------------------------------------------------------------
# Battle engine
# ---------------------------------------------------------------------------

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

        # Set starting positions: player near camera (z=10), opponent far (z=110)
        self.player.pos_z = 10.0
        self.player.pos_x = 0.0
        self.opponent.pos_z = 110.0
        self.opponent.pos_x = 0.0

        self.tick_count: int = 0
        self.running: bool = False
        self._next_id: int = 1

        self.log: list[dict] = []
        self.battle_over: bool = False
        self.winner: str | None = None

        self.projectiles: list[Projectile] = []
        self.delayed_hits: list[DelayedHit] = []

        # Pending finisher: waiting for player mash input
        self._pending_finisher: dict | None = None

        self._lock = threading.Lock()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def start(self):
        self.running = True
        self._loop()

    def stop(self):
        self.running = False

    def set_player_command(self, command: str):
        with self._lock:
            if command in self.player.available_commands:
                self.player.command = command
                self._log_event("command", f"{self.player.name} switches to {command} mode.")

    def set_player_technique(self, technique: str):
        with self._lock:
            if technique in self.player.techniques:
                self.player.command = "Manual"
                self.player._manual_tech = technique

    def resolve_finisher(self, mash_score: int):
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

        # 1. Tick timers + stamina regen
        for f in (self.player, self.opponent):
            f.tick_speed_buffer(t)
            f.tick_cooldown()
            f.tick_status_timers()
            f.stamina = min(100.0, f.stamina + f.stamina_regen)

        # 2. Assess threat and move fighters
        self._assess_threat(self.player, self.opponent)
        self._assess_threat(self.opponent, self.player)
        self._move_fighter(self.player, self.opponent)
        self._move_fighter(self.opponent, self.player)

        # 3. Move projectiles, check collisions, despawn expired
        self._tick_projectiles()

        # 4. Tick delayed-hit timers (WIDE moves)
        self._tick_delayed_hits()

        # 5. Drain HP from damage buffer
        for f in (self.player, self.opponent):
            if f.hp_damage_buffer > 0:
                f.hp_damage_buffer, f.current_hp = damage_tick(
                    f.hp_damage_buffer, f.current_hp
                )

        # 6. Poison HP drain (once per second)
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

        # 7. Check for battle end
        if self._check_end():
            return

        # 8. Wait if finisher resolution pending
        if self._pending_finisher:
            self._emit_state()
            return

        # 9a. Tick windups — fire queued attacks when countdown reaches zero
        self._tick_windup(self.player, self.opponent)
        self._tick_windup(self.opponent, self.player)

        # 9b. Let each fighter start a new action if able (with think delay)
        for attacker, defender in [
            (self.player, self.opponent),
            (self.opponent, self.player),
        ]:
            if not attacker.can_act:
                continue
            if attacker.think_timer == 0:
                attacker.think_timer = random.randint(8, 22)  # 0.27–0.73s pause
                continue
            attacker.think_timer -= 1
            if attacker.think_timer > 0:
                continue
            self._execute_action(attacker, defender)

        # 10. Emit state
        self._emit_state()

    # -----------------------------------------------------------------------
    # Spatial movement AI
    # -----------------------------------------------------------------------

    def _assess_threat(self, f: Fighter, other: Fighter):
        """
        Dynamically adjust preferred_distance based on opponent threat level.
        High threat (healthy opponent) → maintain or increase distance.
        Low threat (tired/weakened opponent) → close in aggressively.
        """
        opp_threat = (other.stamina / 100.0) * 0.5 + (other.current_hp / max(1, other.max_hp)) * 0.5
        # Map threat 0–1 → delta ±5 units around base distance
        delta = (opp_threat - 0.5) * 10.0
        f.preferred_distance = max(3.0, min(60.0, f._base_preferred_distance + delta))

    def _move_fighter(self, f: Fighter, other: Fighter):
        """
        Move fighter toward/away from opponent to maintain preferred_distance.
        Includes: hurt retreat, circling strafe, charge boost for melee,
        knockback, and lateral dodge when a dodgeable projectile is incoming.
        """
        # --- Knockback overrides normal movement ---
        if f.knockback_ticks > 0:
            f.pos_z = max(5.0, min(115.0, f.pos_z + f.knockback_vel_z))
            f.knockback_ticks -= 1
            return

        # --- Hurt retreat: back away after taking a hit ---
        if f.hurt_retreat_timer > 0:
            f.hurt_retreat_timer -= 1
            f.pos_z -= f.move_speed * _sign(other.pos_z - f.pos_z)
            f.pos_z = max(5.0, min(115.0, f.pos_z))
            f.state = "moving"
            # Fall through to X-axis strafing below

        elif f.windup_action is None:
            # --- Z-axis: approach / retreat (frozen during windup) ---
            dist = abs(other.pos_z - f.pos_z)
            target = f.preferred_distance

            # Charge boost: melee fighters sprint when far from the opponent
            if dist > target + 20 and f._base_preferred_distance <= 8:
                effective_speed = f.move_speed * 2.0
            else:
                effective_speed = f.move_speed

            if dist > target + 5:
                f.pos_z += effective_speed * _sign(other.pos_z - f.pos_z)
                f.state = "moving"
            elif dist < target - 5:
                f.pos_z -= effective_speed * _sign(other.pos_z - f.pos_z)
                f.state = "moving"
            else:
                f.state = "idle"

            f.pos_z = max(5.0, min(115.0, f.pos_z))

        # --- X-axis: orbit/circle around opponent ---
        if f.strafe_timer <= 0:
            orbit_offset = random.uniform(20.0, 50.0) * random.choice([-1, 1])
            f.strafe_target_x = max(-65.0, min(65.0, other.pos_x + orbit_offset))
            f.strafe_timer = random.randint(30, 60)
        else:
            f.strafe_timer -= 1

        dx = f.strafe_target_x - f.pos_x
        if abs(dx) > 1.0:
            f.pos_x += _sign(dx) * f.move_speed * 0.45
        f.pos_x = max(-65.0, min(65.0, f.pos_x))

        # --- Lateral dodge for incoming projectiles ---
        for p in self.projectiles:
            if p.defender_name != f.name or not p.dodgeable:
                continue
            dist_z = abs(p.pos_z - f.pos_z)
            ticks_away = dist_z / max(abs(p.vel_z), 0.1)
            if ticks_away < 25 and abs(p.pos_x - f.pos_x) < DODGE_THRESHOLD * 1.5:
                if random.random() < 0.40:
                    direction = 1 if f.pos_x <= 0 else -1
                    f.pos_x = max(-65.0, min(65.0, f.pos_x + direction * f.move_speed * 1.8))
                    f.strafe_target_x = f.pos_x  # prevent immediate drift back

    # -----------------------------------------------------------------------
    # Windup system
    # -----------------------------------------------------------------------

    def _tick_windup(self, attacker: Fighter, defender: Fighter):
        """
        Count down the windup on a queued technique and fire it when done.
        """
        if not attacker.windup_action:
            return
        attacker.windup_ticks_remaining -= 1
        attacker.state = "winding_up"
        if attacker.windup_ticks_remaining <= 0:
            tech_name = attacker.windup_action
            attacker.windup_action = None
            self._fire_windup_technique(attacker, defender, tech_name)

    def _fire_windup_technique(self, attacker: Fighter, defender: Fighter, tech_name: str):
        """
        Execute a SHORT or LONG technique that completed its windup.
        MP has already been deducted; speed buffer already reset.
        """
        if tech_name not in TECHNIQUES:
            return
        tech = TECHNIQUES[tech_name]
        tech_range = tech["range"]

        # Range re-check for SHORT: fighter may not have closed distance in time
        if tech_range == "SHORT":
            dist = abs(defender.pos_z - attacker.pos_z)
            if dist > SHORT_RANGE_THRESHOLD:
                # Too far — refund MP and let fighter retry
                mp_cost = calc_mp_cost(tech["mp_cost"], attacker.brains, attacker.is_sick)
                attacker.current_mp = min(attacker.max_mp, attacker.current_mp + mp_cost)
                attacker.state = "moving"
                return

        hit_chance = calc_hit_chance(
            attacker_speed=attacker.speed,
            victim_speed=defender.speed,
            move_accuracy=tech["accuracy"],
        )
        attacker.state = "attacking"
        type_label = _type_label(tech["type"], defender.def_type)

        # --- LONG move → traveling projectile ---
        if tech_range == "LONG":
            if not roll_hit(hit_chance):
                self._log_event("miss", f"{attacker.name} fires {tech_name}... but it misses!", color="#95a5a6")
                return
            dmg = calc_damage(
                attacker_offense=attacker.effective_offense,
                defender_defense=defender.effective_defense,
                move_power=tech["power"],
                attacker_type=tech["type"],
                defender_type=defender.def_type,
                mastery_count=attacker.mastery_counts.get(tech_name, 0),
                is_enemy=not attacker.is_player,
            )
            attacker.mastery_counts[tech_name] = min(99, attacker.mastery_counts.get(tech_name, 0) + 1)
            dx = defender.pos_x - attacker.pos_x
            dz = defender.pos_z - attacker.pos_z
            dist_to_target = math.sqrt(dx * dx + dz * dz) or 1.0
            vel_x = (dx / dist_to_target) * PROJECTILE_SPEED
            vel_z = (dz / dist_to_target) * PROJECTILE_SPEED
            proj = Projectile(
                id=self._next_id,
                pos_x=attacker.pos_x, pos_z=attacker.pos_z,
                vel_x=vel_x, vel_z=vel_z,
                attacker_name=attacker.name, defender_name=defender.name,
                tech_name=tech_name, damage=dmg,
                status=tech["status"], status_chance=tech.get("status_chance", 0),
                dodgeable=tech.get("dodgeable", True),
            )
            self._next_id += 1
            self.projectiles.append(proj)
            self._log_event("attack", f"{attacker.name} fires {tech_name}{type_label} → {dmg} dmg incoming!", color=attacker.color, damage=dmg)
            return

        # --- SHORT move → instant damage ---
        if not roll_hit(hit_chance):
            self._log_event("miss", f"{attacker.name} uses {tech_name}... but misses!", color="#95a5a6")
            return
        dmg = calc_damage(
            attacker_offense=attacker.effective_offense,
            defender_defense=defender.effective_defense,
            move_power=tech["power"],
            attacker_type=tech["type"],
            defender_type=defender.def_type,
            mastery_count=attacker.mastery_counts.get(tech_name, 0),
            is_enemy=not attacker.is_player,
        )
        defender.hp_damage_buffer = min(9999, defender.hp_damage_buffer + dmg)
        attacker.hit_count += 1
        if dmg > 200:
            attacker.heavy_hit_count += 1
        attacker.mastery_counts[tech_name] = min(99, attacker.mastery_counts.get(tech_name, 0) + 1)

        # Knockback: attacker stumbles back; defender staggers away
        attacker.knockback_ticks = 8
        attacker.knockback_vel_z = -attacker.move_speed * 1.2 * _sign(defender.pos_z - attacker.pos_z)
        defender.knockback_ticks = 6
        defender.knockback_vel_z = attacker.move_speed * 1.0 * _sign(defender.pos_z - attacker.pos_z)
        defender.hurt_retreat_timer = 50  # ~1.7s backing away before re-engaging

        status_msg = ""
        if tech["status"] and roll_status(tech.get("status_chance", 0)):
            defender.apply_status(tech["status"])
            status_msg = f" {defender.name} is {tech['status'].lower()}ed!"
        self._log_event("attack", f"{attacker.name} uses {tech_name}{type_label} → {dmg} dmg!{status_msg}", color=attacker.color, damage=dmg)
        attacker.advance_finisher()
        if attacker.finisher_ready:
            self._trigger_finisher(attacker, defender)

    # -----------------------------------------------------------------------
    # Projectile system
    # -----------------------------------------------------------------------

    def _tick_projectiles(self):
        remaining = []
        for p in self.projectiles:
            p.pos_x += p.vel_x
            p.pos_z += p.vel_z
            p.life -= 1

            defender = self._get_fighter(p.defender_name)

            # Collision check
            if defender and self._projectile_hits(p, defender):
                self._apply_projectile_damage(p, defender)
                continue  # consumed

            # Despawn if expired or past the field
            if p.life <= 0 or p.pos_z < 0 or p.pos_z > 100:
                self._log_event(
                    "projectile_miss",
                    f"{p.attacker_name}'s {p.tech_name} missed — {p.defender_name} evaded!",
                    color="#95a5a6",
                )
                continue

            remaining.append(p)

        self.projectiles = remaining

    def _projectile_hits(self, p: Projectile, defender: Fighter) -> bool:
        """
        For dodgeable projectiles: hit if within DODGE_THRESHOLD x-units AND
        within 4 z-units (close enough to register collision).
        For non-dodgeable: hit as soon as z passes defender's z.
        """
        dz = abs(p.pos_z - defender.pos_z)
        if not p.dodgeable:
            # Non-dodgeable: collision when projectile passes defender's z plane
            return dz < abs(p.vel_z) * 1.5
        else:
            dx = abs(p.pos_x - defender.pos_x)
            return dz < 4.0 and dx < DODGE_THRESHOLD

    def _apply_projectile_damage(self, p: Projectile, defender: Fighter):
        defender.hp_damage_buffer = min(9999, defender.hp_damage_buffer + p.damage)
        attacker = self._get_fighter(p.attacker_name)
        if attacker:
            attacker.hit_count += 1
            if p.damage > 200:
                attacker.heavy_hit_count += 1
            attacker.advance_finisher()
            if attacker.finisher_ready:
                self._trigger_finisher(attacker, defender)
            # Defender staggers backward on hit
            defender.knockback_ticks = 6
            defender.knockback_vel_z = attacker.move_speed * _sign(defender.pos_z - attacker.pos_z)

        status_msg = ""
        if p.status and roll_status(p.status_chance):
            defender.apply_status(p.status)
            status_msg = f" {defender.name} is {p.status.lower()}ed!"

        self._log_event(
            "projectile_hit",
            f"{p.attacker_name}'s {p.tech_name} hits {defender.name} → {p.damage} dmg!{status_msg}",
            color="#f39c12",
            damage=p.damage,
        )

    # -----------------------------------------------------------------------
    # Delayed-hit system (WIDE moves)
    # -----------------------------------------------------------------------

    def _tick_delayed_hits(self):
        remaining = []
        for dh in self.delayed_hits:
            dh.ticks_remaining -= 1
            if dh.ticks_remaining <= 0:
                defender = self._get_fighter(dh.defender_name)
                if defender:
                    self._apply_delayed_damage(dh, defender)
            else:
                remaining.append(dh)
        self.delayed_hits = remaining

    def _apply_delayed_damage(self, dh: DelayedHit, defender: Fighter):
        defender.hp_damage_buffer = min(9999, defender.hp_damage_buffer + dh.damage)
        attacker = self._get_fighter(dh.attacker_name)
        if attacker:
            attacker.hit_count += 1
            attacker.advance_finisher()
            if attacker.finisher_ready:
                self._trigger_finisher(attacker, defender)
            # WIDE hit: defender staggers backward
            defender.knockback_ticks = 8
            defender.knockback_vel_z = attacker.move_speed * _sign(defender.pos_z - attacker.pos_z)

        status_msg = ""
        if dh.status and roll_status(dh.status_chance):
            defender.apply_status(dh.status)
            status_msg = f" {defender.name} is {dh.status.lower()}ed!"

        self._log_event(
            "attack",
            f"{dh.attacker_name}'s {dh.tech_name} lands on {defender.name} → {dh.damage} dmg!{status_msg}",
            color="#e74c3c",
            damage=dh.damage,
        )

    # -----------------------------------------------------------------------
    # Action execution
    # -----------------------------------------------------------------------

    def _execute_action(self, attacker: Fighter, defender: Fighter):
        # Confused? Attack self immediately (no windup — chaos move)
        if attacker.is_confused and confusion_attacks_self():
            self._log_event(
                "status",
                f"{attacker.name} is confused and attacks itself!",
                color="#e67e22",
            )
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

        # Choose technique (aggression boost when opponent is exhausted)
        aggression_boost = defender.stamina < 40.0
        if hasattr(attacker, "_manual_tech") and attacker._manual_tech:
            tech_name = attacker._manual_tech
            attacker._manual_tech = None
            if tech_name not in attacker.techniques or tech_name not in TECHNIQUES:
                tech_name = attacker.choose_technique(aggression_boost)
        else:
            tech_name = attacker.choose_technique(aggression_boost)

        if tech_name is None:
            attacker.reset_speed_buffer()
            self._log_event("info", f"{attacker.name} has no MP left to attack!")
            return

        tech = TECHNIQUES[tech_name]
        tech_range = tech["range"]

        # --- WIDE move → immediate (has its own built-in delay; no windup needed) ---
        if tech_range == "WIDE":
            mp_cost = calc_mp_cost(tech["mp_cost"], attacker.brains, attacker.is_sick)
            if attacker.current_mp < mp_cost:
                attacker.reset_speed_buffer()
                return
            attacker.current_mp -= mp_cost
            attacker.stamina = max(0.0, attacker.stamina - 15.0)

            hit_chance = calc_hit_chance(
                attacker_speed=attacker.speed,
                victim_speed=defender.speed,
                move_accuracy=tech["accuracy"],
            )
            attacker.state = "attacking"
            attacker.reset_speed_buffer()
            type_label = _type_label(tech["type"], defender.def_type)

            if not roll_hit(hit_chance):
                self._log_event("miss", f"{attacker.name} uses {tech_name}... but it fizzles!", color="#95a5a6")
                return

            dmg = calc_damage(
                attacker_offense=attacker.effective_offense,
                defender_defense=defender.effective_defense,
                move_power=tech["power"],
                attacker_type=tech["type"],
                defender_type=defender.def_type,
                mastery_count=attacker.mastery_counts.get(tech_name, 0),
                is_enemy=not attacker.is_player,
            )
            delay = tech.get("delay_ticks", 45)
            dh = DelayedHit(
                id=self._next_id,
                attacker_name=attacker.name,
                defender_name=defender.name,
                tech_name=tech_name,
                damage=dmg,
                status=tech["status"],
                status_chance=tech.get("status_chance", 0),
                ticks_remaining=delay,
            )
            self._next_id += 1
            self.delayed_hits.append(dh)
            attacker.mastery_counts[tech_name] = min(99, attacker.mastery_counts.get(tech_name, 0) + 1)
            self._log_event(
                "wide_warning",
                f"⚡ {attacker.name} charges {tech_name}{type_label}! ({delay // TICK_RATE:.1f}s warning)",
                color="#e74c3c",
            )
            return

        # Range check for SHORT moves — must be close enough before starting windup
        if tech_range == "SHORT":
            dist = abs(defender.pos_z - attacker.pos_z)
            if dist > SHORT_RANGE_THRESHOLD:
                attacker.state = "moving"
                return  # Keep approaching; speed buffer not reset

        # Deduct MP and start 20-tick windup for SHORT/LONG moves
        mp_cost = calc_mp_cost(tech["mp_cost"], attacker.brains, attacker.is_sick)
        if attacker.current_mp < mp_cost:
            attacker.reset_speed_buffer()
            return
        attacker.current_mp -= mp_cost
        attacker.stamina = max(0.0, attacker.stamina - 15.0)

        # Reset speed buffer now — locks out can_act during windup
        attacker.reset_speed_buffer()
        attacker.windup_action = tech_name
        attacker.windup_ticks_remaining = 35 if tech_range == "SHORT" else 20
        attacker.state = "winding_up"

    # -----------------------------------------------------------------------
    # Finisher
    # -----------------------------------------------------------------------

    def _trigger_finisher(self, attacker: Fighter, defender: Fighter):
        attacker.reset_finisher()
        self._log_event(
            "finisher",
            f"✦ {attacker.name} charges a FINISHING MOVE: {attacker.finisher_name}!",
            color="#f39c12",
        )
        if attacker.is_player:
            self._pending_finisher = {"attacker": attacker, "defender": defender}
            self.emit("finisher_ready", {
                "attacker": attacker.name,
                "move": attacker.finisher_name,
                "power": attacker.finisher_power,
            })
        else:
            mash_score = random.randint(60, 90)
            self._apply_finisher_damage(attacker, defender, mash_score)

    def _apply_finisher_damage(self, attacker: Fighter, defender: Fighter, mash_score: int):
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

    def _get_fighter(self, name: str) -> Fighter | None:
        if self.player.name == name:
            return self.player
        if self.opponent.name == name:
            return self.opponent
        return None

    def _log_event(self, event_type: str, message: str, color: str = "#ecf0f1", damage: int = 0):
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
            "projectiles": [p.to_dict() for p in self.projectiles],
            "delayed_hits": [dh.to_dict() for dh in self.delayed_hits],
            "awaiting_finisher": self._pending_finisher is not None,
        })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sign(x: float) -> float:
    return 1.0 if x >= 0 else -1.0


def _type_label(attack_type: str, defend_type: str) -> str:
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
