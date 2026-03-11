"""
FighterData — mirrors the in-game FighterData struct (0x168 bytes per combatant).
Source: SydMontague/DW1-Code dw1.hpp + battle_rel.asm struct offsets.

Key offsets documented inline.
"""

from dataclasses import dataclass, field
from .data import (
    DIGIMON, TECHNIQUES, STATUS_DURATIONS, get_available_commands,
    MOVE_SPEED, PREFERRED_DIST_MELEE, PREFERRED_DIST_RANGED, PREFERRED_DIST_MIXED,
)
from .formulas import speed_buffer_increment, finisher_goal, finisher_increment, SPEED_BUFFER_MAX


@dataclass
class Fighter:
    # -----------------------------------------------------------------------
    # Identity
    # -----------------------------------------------------------------------
    name: str
    is_player: bool = False

    # -----------------------------------------------------------------------
    # Base stats (from Digimon data, may be penalised by sick/injured status)
    # -----------------------------------------------------------------------
    max_hp: int = 0
    max_mp: int = 0
    offense: int = 0
    defense: int = 0
    speed: int = 0
    brains: int = 0
    stage: str = "Rookie"
    def_type: str = "BATTLE"
    color: str = "#ffffff"
    emoji: str = "?"

    # -----------------------------------------------------------------------
    # Current battle stats — mirrors FighterData fields
    # -----------------------------------------------------------------------
    current_hp: int = field(default=0, init=False)
    current_mp: int = field(default=0, init=False)

    # offset 0x2E — hpDamageBuffer (drain animation buffer)
    hp_damage_buffer: int = field(default=0, init=False)

    # offset 0x32 — speedBuffer (0–100; attack allowed when == 100)
    speed_buffer: float = field(default=0.0, init=False)

    # offset 0x18/0x1A — finisher
    finisher_goal_val: int = field(default=0, init=False)
    finisher_progress: int = field(default=0, init=False)
    finisher_ready: bool = field(default=False, init=False)

    # offset 0x28 — cooldown (80 frames after each attack)
    cooldown: int = field(default=0, init=False)

    # offset 0x1C–0x24 — status timers (in ticks)
    poison_timer: int = field(default=0, init=False)
    confusion_timer: int = field(default=0, init=False)
    stun_timer: int = field(default=0, init=False)
    paralysis_timer: int = field(default=0, init=False)

    # offset 0x34 — BattleFlags
    is_sick: bool = field(default=False, init=False)
    is_injured: bool = field(default=False, init=False)

    # -----------------------------------------------------------------------
    # Spatial state (2.5D arena)
    # pos_z=0 → player side (near camera); pos_z=100 → opponent side (far)
    # pos_x=0 → centre; range -60 to +60 (lateral)
    # -----------------------------------------------------------------------
    pos_x: float = field(default=0.0, init=False)
    pos_z: float = field(default=0.0, init=False)
    move_speed: float = field(default=MOVE_SPEED, init=False)
    preferred_distance: float = field(default=35.0, init=False)
    _base_preferred_distance: float = field(default=35.0, init=False)
    state: str = field(default="idle", init=False)  # idle|moving|attacking|hurt|winding_up

    # Stamina (exhaustion meter) — drains per attack, recovers slowly each tick
    stamina: float = field(default=100.0, init=False)
    stamina_regen: float = field(default=0.08, init=False)

    # Idle strafe — fighters pick a new lateral target every 40–80 ticks
    strafe_target_x: float = field(default=0.0, init=False)
    strafe_timer: int = field(default=0, init=False)

    # Knockback — overrides normal z-movement for a few ticks after a hit
    knockback_ticks: int = field(default=0, init=False)
    knockback_vel_z: float = field(default=0.0, init=False)

    # Retreat impulse — set when taking a hit; overrides approach for N ticks
    hurt_retreat_timer: int = field(default=0, init=False)

    # Windup — queues an attack for N ticks before firing
    windup_ticks_remaining: int = field(default=0, init=False)
    windup_action: str | None = field(default=None, init=False)

    # Think delay — set fresh each time can_act fires; pauses before committing
    think_timer: int = field(default=0, init=False)

    # Organic movement state
    wander_angle: float    = field(default=0.0, init=False)  # continuous lateral drift angle
    commit_timer: int      = field(default=0,   init=False)  # ticks locked to committed_z_vel
    committed_z_vel: float = field(default=0.0, init=False)  # locked Z velocity per tick
    post_action_pause: int = field(default=0,   init=False)  # movement hesitation after attack
    feint_cooldown: int    = field(default=0,   init=False)  # ticks until next feint allowed
    feint_steps: int       = field(default=0,   init=False)  # +N=fwd ticks, -N=back ticks

    # Techniques available
    techniques: list = field(default_factory=list)
    finisher_name: str = ""
    finisher_power: int = 0

    # Command selection (player only)
    command: str = "Auto"

    # Mastery counts (per technique) — affects damage bonus
    mastery_counts: dict = field(default_factory=dict)

    # Battle tracking (for post-battle stat gains)
    hit_count: int = field(default=0, init=False)
    heavy_hit_count: int = field(default=0, init=False)
    blocked_count: int = field(default=0, init=False)
    starting_hp: int = field(default=0, init=False)

    def __post_init__(self):
        self.current_hp = self.max_hp
        self.current_mp = self.max_mp
        self.finisher_goal_val = finisher_goal(self.speed)
        self.starting_hp = self.max_hp
        for tech in self.techniques:
            self.mastery_counts[tech] = 0
        self.preferred_distance = float(self._calc_preferred_distance())
        self._base_preferred_distance = self.preferred_distance

    def _calc_preferred_distance(self) -> int:
        """
        Derive preferred combat distance from technique roster.
        Melee brawlers (all SHORT) → close in tight.
        Ranged fighters (all LONG)  → maintain standoff.
        Mixed moveset               → medium range.
        """
        ranges = {TECHNIQUES[t]["range"] for t in self.techniques if t in TECHNIQUES}
        if ranges == {"SHORT"}:
            return PREFERRED_DIST_MELEE
        if "LONG" in ranges and "SHORT" not in ranges:
            return PREFERRED_DIST_RANGED
        return PREFERRED_DIST_MIXED

    # -----------------------------------------------------------------------
    # Properties
    # -----------------------------------------------------------------------

    @property
    def is_poisoned(self) -> bool:
        return self.poison_timer > 0

    @property
    def is_confused(self) -> bool:
        return self.confusion_timer > 0

    @property
    def is_stunned(self) -> bool:
        return self.stun_timer > 0

    @property
    def is_paralysed(self) -> bool:
        return self.paralysis_timer > 0

    @property
    def can_act(self) -> bool:
        """Can the fighter choose and execute an attack this tick?"""
        return (
            not self.is_stunned
            and not self.is_paralysed
            and self.cooldown == 0
            and self.speed_buffer >= SPEED_BUFFER_MAX
        )

    @property
    def available_commands(self) -> list:
        return get_available_commands(self.brains)

    @property
    def effective_offense(self) -> int:
        """Offense with sick/injured penalty applied (× 0.8)."""
        if self.is_sick or self.is_injured:
            return int(self.offense * 0.8)
        return self.offense

    @property
    def effective_defense(self) -> int:
        """Defense with sick/injured penalty applied (× 0.8)."""
        if self.is_sick or self.is_injured:
            return int(self.defense * 0.8)
        return self.defense

    @property
    def hp_pct(self) -> float:
        return self.current_hp / self.max_hp if self.max_hp > 0 else 0.0

    @property
    def mp_pct(self) -> float:
        return self.current_mp / self.max_mp if self.max_mp > 0 else 0.0

    @property
    def speed_pct(self) -> float:
        return self.speed_buffer / SPEED_BUFFER_MAX

    @property
    def finisher_pct(self) -> float:
        if self.finisher_goal_val == 0:
            return 0.0
        return min(1.0, self.finisher_progress / self.finisher_goal_val)

    @property
    def active_statuses(self) -> list:
        statuses = []
        if self.is_poisoned:
            statuses.append("POISON")
        if self.is_confused:
            statuses.append("CONFUSION")
        if self.is_stunned:
            statuses.append("STUN")
        if self.is_paralysed:
            statuses.append("PARALYSIS")
        return statuses

    # -----------------------------------------------------------------------
    # Tick update methods
    # -----------------------------------------------------------------------

    def tick_speed_buffer(self, tick_number: int):
        """
        Increment speed buffer every other tick (even-frame-only check).
        Source: 0x0005AF44 increaseSpeedBuffer — called via load(0x134D66) % 2 == 0
        """
        if tick_number % 2 == 0 and self.speed_buffer < SPEED_BUFFER_MAX:
            increment = speed_buffer_increment(self.speed)
            self.speed_buffer = min(SPEED_BUFFER_MAX, self.speed_buffer + increment)

    def tick_cooldown(self):
        if self.cooldown > 0:
            self.cooldown -= 1

    def tick_status_timers(self):
        if self.poison_timer > 0:
            self.poison_timer -= 1
        if self.confusion_timer > 0:
            self.confusion_timer -= 1
        if self.stun_timer > 0:
            self.stun_timer -= 1
        if self.paralysis_timer > 0:
            self.paralysis_timer -= 1

    def reset_speed_buffer(self):
        """Reset after attacking."""
        self.speed_buffer = 0.0
        self.cooldown = 80  # Set cooldown (0x0005xyzz setCooldown = 80 frames)

    def apply_status(self, status: str):
        duration = STATUS_DURATIONS.get(status, 0)
        if status == "POISON":
            self.poison_timer = duration
        elif status == "CONFUSION":
            self.confusion_timer = duration
        elif status == "STUN":
            self.stun_timer = duration
        elif status == "PARALYSIS":
            self.paralysis_timer = duration

    def advance_finisher(self):
        """
        Advance finisher progress on a successful hit.
        addAmount = finisherGoal * 2 / 100 (0x5ABC0)
        """
        if not self.finisher_ready:
            increment = finisher_increment(self.finisher_goal_val)
            self.finisher_progress = min(self.finisher_goal_val, self.finisher_progress + increment)
            if self.finisher_progress >= self.finisher_goal_val:
                self.finisher_ready = True

    def reset_finisher(self):
        self.finisher_progress = 0
        self.finisher_ready = False

    def choose_technique(self, aggression_boost: bool = False) -> str | None:
        """
        AI/command-based technique selection.

        All-Out  → heaviest available move (highest power) with enough MP
        Careful  → lightest available move (lowest MP cost)
        Defend   → lowest power move (conserve resources)
        Auto     → random weighted by power
        Manual   → same as All-Out (player override handled by server)

        aggression_boost: when True (opponent stamina < 40%), always pick max power.
        """
        available = [
            t for t in self.techniques
            if t in TECHNIQUES and self.current_mp >= TECHNIQUES[t]["mp_cost"]
        ]
        if not available:
            return None

        if aggression_boost or self.command in ("All-Out", "Manual"):
            return max(available, key=lambda t: TECHNIQUES[t]["power"])
        elif self.command == "Careful":
            return min(available, key=lambda t: TECHNIQUES[t]["mp_cost"])
        elif self.command == "Defend":
            return min(available, key=lambda t: TECHNIQUES[t]["power"])
        else:  # Auto — random, weighted by power
            import random
            weights = [TECHNIQUES[t]["power"] for t in available]
            return random.choices(available, weights=weights, k=1)[0]

    # -----------------------------------------------------------------------
    # Serialisation (sent to browser via WebSocket)
    # -----------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "is_player": self.is_player,
            "stage": self.stage,
            "color": self.color,
            "emoji": self.emoji,
            "max_hp": self.max_hp,
            "max_mp": self.max_mp,
            "current_hp": max(0, self.current_hp),
            "current_mp": max(0, self.current_mp),
            "hp_pct": round(self.hp_pct, 4),
            "mp_pct": round(self.mp_pct, 4),
            "speed_pct": round(self.speed_pct, 4),
            "finisher_pct": round(self.finisher_pct, 4),
            "finisher_ready": self.finisher_ready,
            "cooldown": self.cooldown,
            "statuses": self.active_statuses,
            "techniques": self.techniques,
            "available_commands": self.available_commands,
            "command": self.command,
            "can_act": self.can_act,
            "offense": self.offense,
            "defense": self.defense,
            "speed": self.speed,
            "brains": self.brains,
            # Spatial state
            "pos_x": round(self.pos_x, 2),
            "pos_z": round(self.pos_z, 2),
            "state": self.state,
            "preferred_distance": self.preferred_distance,
            "stamina": round(self.stamina, 1),
        }


def make_fighter(digimon_name: str, is_player: bool = False) -> Fighter:
    """Factory: build a Fighter from the DIGIMON data dictionary."""
    data = DIGIMON[digimon_name]
    return Fighter(
        name=digimon_name,
        is_player=is_player,
        max_hp=data["hp"],
        max_mp=data["mp"],
        offense=data["offense"],
        defense=data["defense"],
        speed=data["speed"],
        brains=data["brains"],
        stage=data["stage"],
        def_type=data["def_type"],
        color=data["color"],
        emoji=data["emoji"],
        techniques=list(data["techniques"]),
        finisher_name=data["finisher"],
        finisher_power=data["finisher_power"],
        command="All-Out" if data["brains"] >= 100 else "Auto",
    )
