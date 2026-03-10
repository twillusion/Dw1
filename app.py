"""
Flask + Flask-SocketIO server for the Digimon World 1 battle simulator.

Each connected browser session gets its own BattleEngine instance running
in a background thread. Battle state is pushed to the client
via WebSocket events every tick (~30fps game logic).
"""

from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO, emit, join_room
from engine.battle import BattleEngine
from engine.data import DIGIMON, TECHNIQUES

app = Flask(__name__, static_folder="static", template_folder="static")
app.config["SECRET_KEY"] = "dw1-battle-sim-secret"

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Active battles keyed by session ID
_battles: dict[str, BattleEngine] = {}


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/digimon")
def api_digimon():
    """Return all available Digimon with their stats."""
    result = {}
    for name, data in DIGIMON.items():
        result[name] = {
            **data,
            "name": name,
            "techniques": [
                {
                    "name": t,
                    **TECHNIQUES[t],
                }
                for t in data["techniques"]
                if t in TECHNIQUES
            ],
        }
    return jsonify(result)


@app.route("/api/techniques")
def api_techniques():
    return jsonify(TECHNIQUES)


# ---------------------------------------------------------------------------
# WebSocket events
# ---------------------------------------------------------------------------

@socketio.on("connect")
def on_connect():
    print(f"[WS] Client connected: {_sid()}")


@socketio.on("disconnect")
def on_disconnect():
    sid = _sid()
    if sid in _battles:
        _battles[sid].stop()
        del _battles[sid]
    print(f"[WS] Client disconnected: {sid}")


@socketio.on("start_battle")
def on_start_battle(data):
    """
    data = {
        "player": "Greymon",
        "opponent": "Garurumon"
    }
    """
    sid = _sid()

    # Stop any existing battle for this session
    if sid in _battles:
        _battles[sid].stop()

    player_name = data.get("player", "Agumon")
    opponent_name = data.get("opponent", "Greymon")

    if player_name not in DIGIMON or opponent_name not in DIGIMON:
        emit("error", {"message": "Unknown Digimon name."})
        return

    def emit_fn(event: str, payload: dict):
        socketio.emit(event, payload, room=sid)

    engine = BattleEngine(
        player_name=player_name,
        opponent_name=opponent_name,
        emit_fn=emit_fn,
    )
    _battles[sid] = engine

    # Join the session's own room so emit_fn can target it
    join_room(sid)

    # Start the battle in a background thread
    import threading
    threading.Thread(target=engine.start, daemon=True).start()

    emit("battle_started", {
        "player": engine.player.to_dict(),
        "opponent": engine.opponent.to_dict(),
    })


@socketio.on("player_command")
def on_player_command(data):
    """data = { "command": "All-Out" }"""
    sid = _sid()
    engine = _battles.get(sid)
    if engine:
        engine.set_player_command(data.get("command", "Auto"))


@socketio.on("player_technique")
def on_player_technique(data):
    """data = { "technique": "Nova Blast" }"""
    sid = _sid()
    engine = _battles.get(sid)
    if engine:
        engine.set_player_technique(data.get("technique", ""))


@socketio.on("finisher_result")
def on_finisher_result(data):
    """
    data = { "mash_score": 75 }
    Called when the browser finishes the button-mash mini-game.
    """
    sid = _sid()
    engine = _battles.get(sid)
    if engine:
        engine.resolve_finisher(data.get("mash_score", 50))


@socketio.on("stop_battle")
def on_stop_battle(_data=None):
    sid = _sid()
    if sid in _battles:
        _battles[sid].stop()
        del _battles[sid]
    emit("battle_stopped", {})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sid() -> str:
    from flask import request
    return request.sid


if __name__ == "__main__":
    print("Starting Digimon World 1 Battle Simulator...")
    print("Open http://localhost:5000 in your browser")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
