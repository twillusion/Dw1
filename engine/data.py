"""
Static game data for Digimon World 1 battle simulator.
Stats and techniques sourced from community documentation and the
SydMontague/DW1-Code reverse-engineering project.

Technique MP costs are stored as in-game values (moveData.mpCost * 3).
Type chart values from ROM offset 0x125F70 (approximated where exact
extraction is unavailable).
"""

# ---------------------------------------------------------------------------
# Type indices
# ---------------------------------------------------------------------------
FIRE   = "FIRE"
BATTLE = "BATTLE"
AIR    = "AIR"
EARTH  = "EARTH"
ICE    = "ICE"
MECH   = "MECH"
FILTH  = "FILTH"

ALL_TYPES = [FIRE, BATTLE, AIR, EARTH, ICE, MECH, FILTH]

# ---------------------------------------------------------------------------
# Type effectiveness chart — TYPE_CHART[attacker_type][defender_type]
# Values: 2 (quarter), 5 (half), 10 (neutral), 15 (1.5×), 20 (double)
# Sourced from ROM 0x125F70 (7×7 table, stride 7); exact values approximated
# from community knowledge where ROM extraction is unavailable.
# ---------------------------------------------------------------------------
TYPE_CHART = {
    #           FIRE  BATTLE  AIR   EARTH  ICE   MECH  FILTH
    FIRE:   [   10,   10,    10,    5,    20,    5,    10  ],
    BATTLE: [   10,   10,    10,   10,    10,   10,    10  ],
    AIR:    [   10,   10,    10,   15,    10,    5,    10  ],
    EARTH:  [    5,   10,     5,   10,    15,   20,    10  ],
    ICE:    [   20,   10,    10,    5,    10,   10,    10  ],
    MECH:   [   15,   10,    15,    5,    10,   10,    10  ],
    FILTH:  [   10,   15,    10,   10,    10,   10,    10  ],
}

# ---------------------------------------------------------------------------
# Techniques
# Data layout matches ROM tech table at 0x126240, stride 0x10 per entry.
# Fields: power (int16), mp_cost (actual in-game = stored × 3),
#         range (SHORT/LONG/WIDE), element type, status effect, accuracy (0-100),
#         status_chance (0-100)
# Source: grindosaur.com/en/games/digimon-world/techniques + DW1-Code struct
# ---------------------------------------------------------------------------
TECHNIQUES = {
    # --- FIRE ---
    # dodgeable=True  → small/fast projectile, lateral movement can avoid it
    # dodgeable=False → wide beam / homing; statistical miss only, not physical dodge
    # delay_ticks     → WIDE moves only: frames of warning before damage lands
    "Pepper Breath": {
        "power": 50, "mp_cost": 18, "range": "LONG",
        "type": FIRE, "status": None, "accuracy": 90, "status_chance": 0,
        "dodgeable": True,
        "description": "A weak fireball. Agumon's signature move."
    },
    "Pyro Sphere": {
        "power": 110, "mp_cost": 42, "range": "LONG",
        "type": FIRE, "status": None, "accuracy": 85, "status_chance": 0,
        "dodgeable": True,
        "description": "A larger fireball with more stopping power."
    },
    "Nova Blast": {
        "power": 160, "mp_cost": 66, "range": "WIDE",
        "type": FIRE, "status": None, "accuracy": 80, "status_chance": 0,
        "dodgeable": False, "delay_ticks": 45,
        "description": "Greymon's powerful wave of flames."
    },
    "Prominence Beam": {
        "power": 220, "mp_cost": 90, "range": "LONG",
        "type": FIRE, "status": None, "accuracy": 75, "status_chance": 0,
        "dodgeable": False,   # sustained beam, must block not dodge
        "description": "A concentrated beam of intense fire."
    },

    # --- BATTLE ---
    "Sonic Jab": {
        "power": 30, "mp_cost": 18, "range": "SHORT",
        "type": BATTLE, "status": None, "accuracy": 95, "status_chance": 0,
        "dodgeable": False,
        "description": "Rapid-fire punches at close range."
    },
    "Megaton Punch": {
        "power": 85, "mp_cost": 30, "range": "SHORT",
        "type": BATTLE, "status": None, "accuracy": 90, "status_chance": 0,
        "dodgeable": False,
        "description": "A heavy punch that launches the foe."
    },
    "Thunder Claw": {
        "power": 130, "mp_cost": 48, "range": "SHORT",
        "type": BATTLE, "status": None, "accuracy": 85, "status_chance": 0,
        "dodgeable": False,
        "description": "Crackling claws strike with lightning speed."
    },
    "Hyper Knuckle": {
        "power": 190, "mp_cost": 72, "range": "SHORT",
        "type": BATTLE, "status": None, "accuracy": 80, "status_chance": 0,
        "dodgeable": False,
        "description": "Devastating close-range strike."
    },

    # --- AIR ---
    "Spinning Shot": {
        "power": 55, "mp_cost": 18, "range": "LONG",
        "type": AIR, "status": None, "accuracy": 90, "status_chance": 0,
        "dodgeable": True,    # small feathers, can sidestep
        "description": "Feathers fired in a spinning pattern."
    },
    "Wing Blade": {
        "power": 100, "mp_cost": 36, "range": "LONG",
        "type": AIR, "status": None, "accuracy": 85, "status_chance": 0,
        "dodgeable": True,
        "description": "A razor-sharp gust of wind."
    },
    "Storm of Silence": {
        "power": 140, "mp_cost": 66, "range": "WIDE",
        "type": AIR, "status": "CONFUSION", "accuracy": 80, "status_chance": 40,
        "dodgeable": False, "delay_ticks": 45,
        "description": "A howling storm that may confuse enemies."
    },

    # --- EARTH ---
    "Danger Sting": {
        "power": 60, "mp_cost": 24, "range": "SHORT",
        "type": EARTH, "status": "POISON", "accuracy": 90, "status_chance": 35,
        "dodgeable": False,
        "description": "A venomous strike that may poison."
    },
    "Earth Shaker": {
        "power": 110, "mp_cost": 48, "range": "WIDE",
        "type": EARTH, "status": None, "accuracy": 78, "status_chance": 0,
        "dodgeable": False, "delay_ticks": 45,
        "description": "Triggers a ground-shaking tremor."
    },
    "Terra Force": {
        "power": 350, "mp_cost": 120, "range": "WIDE",
        "type": EARTH, "status": None, "accuracy": 65, "status_chance": 0,
        "dodgeable": False, "delay_ticks": 45,
        "description": "WarGreymon's ultimate technique. Immense power."
    },

    # --- ICE ---
    "Blizzard": {
        "power": 85, "mp_cost": 30, "range": "LONG",
        "type": ICE, "status": None, "accuracy": 85, "status_chance": 0,
        "dodgeable": False,   # wide icy blast, can't sidestep
        "description": "A sharp blizzard of icy wind."
    },
    "Subzero Ice Punch": {
        "power": 140, "mp_cost": 54, "range": "SHORT",
        "type": ICE, "status": "PARALYSIS", "accuracy": 82, "status_chance": 30,
        "dodgeable": False,
        "description": "A freezing punch that may paralyse."
    },
    "Ice Needle": {
        "power": 60, "mp_cost": 24, "range": "LONG",
        "type": ICE, "status": None, "accuracy": 88, "status_chance": 0,
        "dodgeable": True,    # thin ice spikes, can sidestep
        "description": "Sharp spikes of ice launched at speed."
    },

    # --- MECH ---
    "Mega Claw": {
        "power": 120, "mp_cost": 42, "range": "SHORT",
        "type": MECH, "status": None, "accuracy": 88, "status_chance": 0,
        "dodgeable": False,
        "description": "Steel claws tear through armour."
    },
    "Giga Blaster": {
        "power": 210, "mp_cost": 78, "range": "LONG",
        "type": MECH, "status": None, "accuracy": 72, "status_chance": 0,
        "dodgeable": False,   # arm cannon beam, unavoidable
        "description": "MetalGreymon's arm cannon fires at full power."
    },
    "Genocide Attack": {
        "power": 310, "mp_cost": 108, "range": "WIDE",
        "type": MECH, "status": None, "accuracy": 65, "status_chance": 0,
        "dodgeable": False, "delay_ticks": 45,
        "description": "A devastating barrage of missiles."
    },

    # --- FILTH ---
    "Odor Spray": {
        "power": 40, "mp_cost": 18, "range": "WIDE",
        "type": FILTH, "status": "STUN", "accuracy": 88, "status_chance": 45,
        "dodgeable": False, "delay_ticks": 45,
        "description": "A foul cloud that may briefly stun."
    },
    "Poison Claw": {
        "power": 70, "mp_cost": 30, "range": "SHORT",
        "type": FILTH, "status": "POISON", "accuracy": 85, "status_chance": 40,
        "dodgeable": False,
        "description": "Toxic claws that seep venom."
    },
}

# ---------------------------------------------------------------------------
# Digimon roster — ~10 iconic Digimon from DW1
# Stats are approximate values typical for a well-raised specimen at that
# evolution stage, cross-referenced with DW1 stat caps and community data.
# def_type: the Digimon's elemental affinity (used as defender type in formula)
# techniques: list of known technique names
# ---------------------------------------------------------------------------
DIGIMON = {
    "Agumon": {
        "stage": "Rookie",
        "hp": 500, "mp": 200,
        "offense": 100, "defense": 80, "speed": 120, "brains": 100,
        "def_type": FIRE,
        "techniques": ["Pepper Breath", "Sonic Jab"],
        "finisher": "Pepper Breath",
        "finisher_power": 200,
        "color": "#e87c1e",
        "emoji": "🦎",
    },
    "Greymon": {
        "stage": "Champion",
        "hp": 1200, "mp": 500,
        "offense": 320, "defense": 260, "speed": 290, "brains": 200,
        "def_type": FIRE,
        "techniques": ["Nova Blast", "Mega Claw", "Pyro Sphere"],
        "finisher": "Nova Blast",
        "finisher_power": 420,
        "color": "#c0392b",
        "emoji": "🦖",
    },
    "MetalGreymon": {
        "stage": "Ultimate",
        "hp": 2200, "mp": 900,
        "offense": 560, "defense": 450, "speed": 400, "brains": 360,
        "def_type": MECH,
        "techniques": ["Giga Blaster", "Mega Claw", "Nova Blast"],
        "finisher": "Giga Blaster",
        "finisher_power": 650,
        "color": "#7f8c8d",
        "emoji": "🤖",
    },
    "WarGreymon": {
        "stage": "Mega",
        "hp": 3500, "mp": 1200,
        "offense": 800, "defense": 660, "speed": 700, "brains": 600,
        "def_type": EARTH,
        "techniques": ["Terra Force", "Thunder Claw", "Mega Claw"],
        "finisher": "Terra Force",
        "finisher_power": 999,
        "color": "#d35400",
        "emoji": "⚔️",
    },
    "Garurumon": {
        "stage": "Champion",
        "hp": 900, "mp": 420,
        "offense": 300, "defense": 220, "speed": 460, "brains": 260,
        "def_type": ICE,
        "techniques": ["Blizzard", "Sonic Jab", "Ice Needle"],
        "finisher": "Blizzard",
        "finisher_power": 380,
        "color": "#3498db",
        "emoji": "🐺",
    },
    "WereGarurumon": {
        "stage": "Ultimate",
        "hp": 1800, "mp": 700,
        "offense": 600, "defense": 360, "speed": 620, "brains": 300,
        "def_type": BATTLE,
        "techniques": ["Thunder Claw", "Hyper Knuckle", "Sonic Jab"],
        "finisher": "Hyper Knuckle",
        "finisher_power": 580,
        "color": "#9b59b6",
        "emoji": "🐾",
    },
    "MetalGarurumon": {
        "stage": "Mega",
        "hp": 3200, "mp": 1100,
        "offense": 760, "defense": 620, "speed": 760, "brains": 560,
        "def_type": ICE,
        "techniques": ["Blizzard", "Giga Blaster", "Genocide Attack"],
        "finisher": "Genocide Attack",
        "finisher_power": 950,
        "color": "#2980b9",
        "emoji": "🐺",
    },
    "Angemon": {
        "stage": "Champion",
        "hp": 1000, "mp": 700,
        "offense": 280, "defense": 280, "speed": 280, "brains": 420,
        "def_type": BATTLE,
        "techniques": ["Thunder Claw", "Spinning Shot", "Wing Blade"],
        "finisher": "Thunder Claw",
        "finisher_power": 440,
        "color": "#f1c40f",
        "emoji": "😇",
    },
    "Birdramon": {
        "stage": "Champion",
        "hp": 780, "mp": 520,
        "offense": 310, "defense": 200, "speed": 520, "brains": 200,
        "def_type": AIR,
        "techniques": ["Spinning Shot", "Storm of Silence", "Wing Blade"],
        "finisher": "Storm of Silence",
        "finisher_power": 410,
        "color": "#e74c3c",
        "emoji": "🦅",
    },
    "SkullGreymon": {
        "stage": "Ultimate",
        "hp": 2000, "mp": 500,
        "offense": 720, "defense": 300, "speed": 500, "brains": 100,
        "def_type": EARTH,
        "techniques": ["Earth Shaker", "Danger Sting", "Mega Claw"],
        "finisher": "Earth Shaker",
        "finisher_power": 600,
        "color": "#1abc9c",
        "emoji": "💀",
    },
}

# Status effect durations in ticks (at 30 ticks/sec)
# Sourced from FighterData timer fields + observed game behaviour
STATUS_DURATIONS = {
    "POISON":    300,   # ~10s, causes periodic HP drain
    "CONFUSION": 300,   # ~10s, 70% chance attacks self
    "PARALYSIS": 300,   # ~10s, cannot act
    "STUN":       90,   # ~3s, brief stun
}

# Poison tick: HP drained per 30 ticks (1 second) while poisoned
# Higher stage Digimon drain faster (approximated from game observations)
POISON_DRAIN_PER_SEC = {
    "Rookie":   15,
    "Champion": 25,
    "Ultimate": 40,
    "Mega":     60,
}

# Brains thresholds → available commands
# Source: game mechanics / community documentation
BRAINS_COMMANDS = [
    (0,   ["Auto"]),
    (100, ["Auto", "All-Out"]),
    (200, ["Auto", "All-Out", "Careful"]),
    (300, ["Auto", "All-Out", "Careful", "Keep Back"]),
    (400, ["Auto", "All-Out", "Careful", "Keep Back", "Defend"]),
    (500, ["Auto", "All-Out", "Careful", "Keep Back", "Defend", "Manual"]),
]


def get_available_commands(brains: int) -> list[str]:
    cmds = ["Auto"]
    for threshold, commands in BRAINS_COMMANDS:
        if brains >= threshold:
            cmds = commands
    return cmds


def get_type_factor(attacker_type: str, defender_type: str) -> int:
    """Returns the type effectiveness factor (2/5/10/15/20)."""
    defender_idx = ALL_TYPES.index(defender_type)
    return TYPE_CHART[attacker_type][defender_idx]


# ---------------------------------------------------------------------------
# Spatial / movement constants
# ---------------------------------------------------------------------------

# Distance (field units) within which SHORT range attacks can land
SHORT_RANGE_THRESHOLD = 25

# Fixed movement speed for all Digimon (units per tick at 30 ticks/sec)
# Can be individualised per Digimon in a future iteration
MOVE_SPEED = 0.72

# Preferred standoff distances (field units)
PREFERRED_DIST_MELEE  = 18   # all SHORT range → close in
PREFERRED_DIST_RANGED = 45   # all LONG range  → maintain distance
PREFERRED_DIST_MIXED  = 32   # mixed moveset   → medium range

# Projectile travel speed (field units per tick)
PROJECTILE_SPEED = 1.625

# Collision radius: projectile hits if it gets within this many x-units of the
# defender. Intentionally lenient so ranged attacks land most of the time.
DODGE_THRESHOLD = 14
