"""Label game sounds whose real names were recovered (joaat(name) & 0x1FFFFFFF = stream id), so the controller
speaker plays the game's own recordings for them. Writes tools/trigger_lab/data/sound_labels.json
(merged with existing labels; keys "<bank>/<first stream id>", like the lab's Sounds page)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "trigger_lab"))
from gameaudio import awc  # noqa: E402
from gameaudio.library import GameAudio  # noqa: E402

GAME = Path("C:/steam/steamapps/common/Red Dead Redemption 2")
LABELS = ROOT / "trigger_lab" / "data" / "sound_labels.json"

# recovered names (tools/awc/namehunt2.py, sndbrute.cpp) -> role
NAMED = {
    "WEAPONS": {
        "draw": ["revolver_draw2", "revolver_draw3", "revolver_draw4"],
        "holster": ["revolver_holster1", "revolver_holster2", "revolver_holster3"],
        "lasso_throw": ["lasso_whoosh_1", "lasso_whoosh_2", "lasso_whoosh_3"],
        "rope_jerk": ["lasso_pull_01", "lasso_pull_04", "lasso_pull_05", "lasso_pull_10"],
        "rope_creak": ["lasso_stress_01", "lasso_stress_02", "lasso_stress_03"],
        "knife_graze": ["knife_graze_1", "knife_graze_2", "knife_graze_3"],
    },
}


def main():
    labels = json.loads(LABELS.read_text("utf-8")) if LABELS.exists() else {}
    lib = GameAudio(GAME, LABELS)
    found = 0
    for bank, roles in NAMED.items():
        by_id = {awc.joaat(n) & 0x1FFFFFFF: (role, n) for role, names in roles.items() for n in names}
        for s in lib.sounds(bank):
            hit = next((by_id[i] for i in s.ids if i in by_id), None)
            if hit:
                labels[f"{bank}/{s.key}"] = hit[0]
                found += 1
                print(f"{bank}/{s.key} = {hit[0]} ({hit[1]}, {s.seconds:.2f} s)")
    LABELS.write_text(json.dumps(labels, indent=2, sort_keys=True), encoding="utf-8")
    print(f"{found} sounds labelled -> {LABELS}")


if __name__ == "__main__":
    main()
