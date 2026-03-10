"""
Battle formulas reverse-engineered from Digimon World 1 (PS1).

Primary source: SydMontague/DW1-Code (BTL_REL.BIN disassembly)
Secondary source: SydMontague/DW1-SydPatches (Battle.cpp, dw1.hpp)

All formula reconstructions are documented with their origin address where known.
"""

import random
from .data import get_type_factor, STATUS_DURATIONS


# ---------------------------------------------------------------------------
# Damage calculation
# Source: BTL_REL.BIN 0x0005BEB8 – 0x0005C1D8
# ---------------------------------------------------------------------------

def calc_damage(
    attacker_offense: int,
    defender_defense: int,
    move_power: int,
    attacker_type: str,
    defender_type: str,
    is_finisher: bool = False,
    mastery_count: int = 0,
    is_enemy: bool = False,
) -> int:
    """
    Core damage formula (BTL_REL.BIN 0x5BEB8).

    Normal move:
        type_factor = type_chart[attacker_type][defender_type]   # 2/5/10/15/20
        off_vs_def  = attacker_offense - defender_defense
        damage      = (off_vs_def + move_power) * type_factor / 17
        damage     *= rand(90–110) / 100                          # ±10% variance

    Finisher (techId 0x3A–0x70):
        Bypasses the off_vs_def subtraction — uses raw movePower only.
        damage = move_power * type_factor / 17

    Mastery bonus (partner only, 0x5C12C):
        if mastery >= 41:  damage = damage * mastery / 20
    Enemy random factor (0x5C14C):
        damage *= (rand(101) + 100) / 100    # ×1.00–×2.00

    Final clamp: [1, 9999]
    """
    type_factor = get_type_factor(attacker_type, defender_type)

    if is_finisher:
        # Finisher bypasses defense (0x5BF7C–0x5BFB4)
        base = move_power
    else:
        off_vs_def = attacker_offense - defender_defense
        base = off_vs_def + move_power

    # Core multiply then divide by 17 (magic constant 0x88888889 >> 4)
    damage = (base * type_factor) // 17

    # Mastery bonus for partner Digimon (0x5C12C–0x5C170)
    if not is_enemy and mastery_count >= 41:
        damage = damage * mastery_count // 20

    # Enemy random variance: rand(101)+100 → ×1.00–×2.00 (0x5C14C)
    if is_enemy:
        damage = damage * (random.randint(0, 101) + 100) // 100

    # General ±10% variance: rand(21)+90 → ×0.90–×1.10 (0x5C174)
    variance = random.randint(0, 21) + 90
    damage = damage * variance // 100

    # Minimum 1, maximum 9999 (0x5C1D8)
    return max(1, min(9999, damage))


def apply_sick_penalty(stat: int) -> int:
    """
    Sick/injured stat penalty: all combat stats × 0.8
    Source: combatInit.asm / dw1.hpp status flag 0x0060
    """
    return int(stat * 0.8)


# ---------------------------------------------------------------------------
# Speed buffer (attack rate)
# Source: BTL_REL.BIN 0x0005AF44 (increaseSpeedBuffer)
# ---------------------------------------------------------------------------

SPEED_BUFFER_MAX = 100

def speed_buffer_increment(speed: int) -> int:
    """
    Per-frame speed buffer increment (called every OTHER frame).
    increment = (speed / 100) + 1
    Buffer fills from 0 to 100; attack allowed when buffer == 100.

    At speed=100: +2 every 2 frames → 100 frames to fill (~3.3s at 30fps)
    At speed=500: +6 every 2 frames → ~33 frames to fill (~1.1s at 30fps)
    At speed=999: +10 every 2 frames → 20 frames to fill (~0.67s at 30fps)
    """
    return (speed // 100) + 1


def ticks_to_attack(speed: int) -> float:
    """
    How many ticks (at 30 ticks/sec) until a fresh Digimon can first attack.
    The speed buffer is updated every other tick.
    """
    increment = speed_buffer_increment(speed)
    # Each 2 ticks, buffer += increment; need to reach 100
    ticks_per_fill = (SPEED_BUFFER_MAX / increment) * 2
    return ticks_per_fill


# ---------------------------------------------------------------------------
# Hit chance
# Source: BTL_REL.BIN 0x0005BBE4 (getChanceToHit)
# ---------------------------------------------------------------------------

def calc_hit_chance(
    attacker_speed: int,
    victim_speed: int,
    move_accuracy: int,
    victim_in_idle: bool = False,
) -> int:
    """
    Hit probability calculation (0x5BBE4).

    attackerSpeedAdj = attacker_speed * 0.1
    speedDiff        = victim_speed - attackerSpeedAdj
    blockFactor      = (accuracy / 2) * speedDiff / 1000
    chanceToHit      = accuracy - blockFactor
    chanceToHit      = clamp(0, 100)

    If victim is in idle animation (anim 0x21 or 0x22): blockFactor *= 1.2
    """
    attacker_adj = attacker_speed * 0.1
    speed_diff = victim_speed - attacker_adj

    block_factor = (move_accuracy / 2) * speed_diff / 1000

    if victim_in_idle:
        block_factor *= 1.2

    chance = move_accuracy - block_factor
    return max(0, min(100, int(chance)))


def roll_hit(chance: int) -> bool:
    return random.randint(1, 100) <= chance


# ---------------------------------------------------------------------------
# MP cost
# Source: getMPCost.asm / dw1.hpp
# ---------------------------------------------------------------------------

def calc_mp_cost(base_mp_cost: int, brains: int, is_sick: bool = False) -> int:
    """
    Actual MP cost formula.
    Base stored as in-game value (already × 3 from ROM stored byte).

    Brains discount (partner only):
        >= 999: × 0.80
        >= 900: × 0.85
        >= 800: × 0.90
        >= 700: × 0.95

    Sick/injured penalty: × 1.5
    """
    cost = base_mp_cost

    if brains >= 999:
        cost = int(cost * 0.80)
    elif brains >= 900:
        cost = int(cost * 0.85)
    elif brains >= 800:
        cost = int(cost * 0.90)
    elif brains >= 700:
        cost = int(cost * 0.95)

    if is_sick:
        cost = int(cost * 1.5)

    return max(1, cost)


# ---------------------------------------------------------------------------
# Finishing move
# Source: addFinisherValue.asm (0x0005ABC0), combatInit.asm
# ---------------------------------------------------------------------------

def finisher_goal(speed: int) -> int:
    """
    finisherGoal = 3000 - speed  (combatInit.asm)
    Represents how many "finisher points" are needed.
    """
    return max(500, 3000 - speed)


def finisher_increment(goal: int) -> int:
    """
    Per-hit finisher progress gain: goal * 2 / 100 ≈ 4% of goal (0x5ABC0).
    """
    return max(1, goal * 2 // 100)


def calc_finisher_damage(
    move_power: int,
    attacker_type: str,
    defender_type: str,
    mash_score: int,  # 0–100 representing player button-mash performance
) -> int:
    """
    Finisher damage (0x5BF7C–0x5BFB4).

    Bypasses offense vs defense. Mash score doubles damage (score 100 = ×2.0).
    type_factor = type_chart[attacker_type][defender_type]
    damage = move_power * type_factor / 17
    damage *= 1.0 + (mash_score / 100)   # ×1.0–×2.0 based on mashing
    """
    type_factor = get_type_factor(attacker_type, defender_type)
    base = move_power * type_factor // 17
    mash_multiplier = 1.0 + (mash_score / 100.0)
    damage = int(base * mash_multiplier)

    # Finisher variance: ±10%
    variance = random.randint(0, 21) + 90
    damage = damage * variance // 100

    return max(1, min(9999, damage))


# ---------------------------------------------------------------------------
# Damage drain (visual tick-based HP drain)
# Source: SydMontague/DW1-SydPatches Battle.cpp damageTick()
# ---------------------------------------------------------------------------

def damage_tick(hp_damage_buffer: int, current_hp: int) -> tuple[int, int]:
    """
    Each tick, drain HP from the buffer in tiered chunks.
    This creates the characteristic DW1 damage number drain animation.

    Source: Battle.cpp damageTick() — NOTE: original runs all branches
    simultaneously per tick (not if/else), creating rapid multi-chunk drain.
    """
    if hp_damage_buffer > 999:
        current_hp -= 900
        hp_damage_buffer -= 900
    if hp_damage_buffer > 99:
        current_hp -= 80
        hp_damage_buffer -= 80
    if hp_damage_buffer > 9:
        current_hp -= 6
        hp_damage_buffer -= 6
    if hp_damage_buffer > 0:
        current_hp -= 1
        hp_damage_buffer -= 1

    if current_hp <= 0:
        current_hp = 0
        hp_damage_buffer = 0

    return hp_damage_buffer, current_hp


# ---------------------------------------------------------------------------
# Status effect helpers
# ---------------------------------------------------------------------------

def roll_status(status_chance: int) -> bool:
    """Returns True if the status effect is successfully applied."""
    return random.randint(1, 100) <= status_chance


def confusion_attacks_self() -> bool:
    """Confused Digimon: 70% chance attacks self, 30% attacks correctly."""
    return random.randint(1, 100) <= 70
