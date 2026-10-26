"""Camp life from the game: bites / sips / puffs (the 'ApplyStat' anim event of the item interaction),
gun cleaning (its item-interaction states), brushing / feeding the horse (the prompt event + each 'INTERACT'),
skinning (loot events), stowing / lifting pelts and carcasses, picking herbs, bathing, crafting, cooking."""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "mod" / "src"


def edit(name, pairs):
    p = SRC / name
    s = p.read_text(encoding="utf-8")
    for a, b in pairs:
        if a not in s:
            raise SystemExit(f"{name}: not found: {a[:90]}")
        s = s.replace(a, b, 1)
    p.write_text(s, encoding="utf-8")


if "GET_ITEM_INTERACTION_STATE" not in (SRC / "natives.h").read_text(encoding="utf-8"):
    edit("natives.h", [(
        "inline bool GET_TASK_FISHING(Ped p, void* data)",
        r'''// camp life
inline Hash GET_ITEM_INTERACTION_STATE(Ped p) { return invoke<Hash>(0x6AA3DCA2C6F5EB6Dull, p); }
inline bool HAS_ANIM_EVENT_FIRED(Entity e, Hash ev) { return invoke<int>(0x5851CC48405F4A07ull, e, ev) != 0; }
inline bool IS_ANIMAL_INTERACTION_RUNNING(Ped p) { return invoke<int>(0x7FC84E85D98F063Dull, p) != 0; }
inline bool GET_IS_ANIMAL(Entity e) { return invoke<int>(0x9A100F1CF4546629ull, e) != 0; }
inline Hash GET_ACTIVE_DYNAMIC_SCENARIO(Ped p) { return invoke<Hash>(0xC22AA08A8ADB87D4ull, p); }
inline bool GET_TASK_FISHING(Ped p, void* data)''')])

edit("world.h", [
    ("enum Type { Damage, Gunfire, HitConfirm, Footstep, Hoof, Land, Climb, Door, Ack, Honor, Minigame, Horse } type;",
     "enum Type { Damage, Gunfire, HitConfirm, Footstep, Hoof, Land, Climb, Door, Ack, Honor, Minigame, Horse, Life } type;"),
    ("    bool thunder = false, indoors = false;",
     "    bool thunder = false, indoors = false;\n"
     "    std::string activity;          // clean_gun, skin, scrub, craft, cook (a texture while it lasts)\n"
     "    float activity_pan = 0;"),
    ("    std::string mg_state_;",
     "    std::string mg_state_;\n"
     "    // camp life\n"
     "    double life_poll_t_ = 0, last_apply_t_ = 0, last_interact_t_ = 0, care_until_ = 0, care_start_ = 0, skin_until_ = 0;\n"
     "    bool smoking_ = false, drinking_ = false, eating_ = false, bathing_ = false;\n"
     "    uint32_t last_item_ = 0;\n"
     "    std::string care_;"),
])

edit("world.cpp", [
    # item-state table
    ("// ---------------- bodies: footfalls from the real legs ----------------",
     r'''// ---------------- camp life ----------------
// item-interaction states that mean eating, drinking, smoking, cleaning a gun
static const char* item_kind(uint32_t state) {
    struct Entry { uint32_t hash; const char* kind; };
    static const Entry kStates[] = {
#include "item_states.inc"
    };
    for (const auto& e : kStates)
        if (e.hash == state) return e.kind;
    return "";
}

// ---------------- bodies: footfalls from the real legs ----------------'''),
    # events: replace the calm-only loop with the full one
    ("""    // --- the game's events: the horse calmed / patted (by you or your "easy") ---
    {
        static const Hash kCalmPed = 0x89AB08C3;            // EVENT_CALM_PED: calmer, mount, calm type, fully calmed
        int n_ev = GET_NUMBER_OF_EVENTS(0);
        for (int i = 0; i < n_ev; ++i) {
            if (GET_EVENT_AT_INDEX(0, i) != kCalmPed) continue;
            alignas(8) uint64_t d[4] = {};
            if (!GET_EVENT_DATA(0, i, d, 4) || int(uint32_t(d[0])) != me) continue;
            int type = int(uint32_t(d[2]));
            LOGD("horse calmed (type %d, fully %d)", type, int(uint32_t(d[3])));
            ev.push_back({WorldEvent::Horse, 0, type >= 3 ? 1.0f : 0.7f, "calm"});
        }
    }""",
     r'''    // --- the game's events (8-byte slots; sizes must match exactly) ---
    {
        static const Hash kCalmPed = 0x89AB08C3;      // calmer, mount, calm type, fully calmed
        static const Hash kPrompt = 0x52AE9189;       // EVENT_PLAYER_PROMPT_TRIGGERED: [0] prompt type (49 brush, 50 feed)
        static const Hash kCalcLoot = 0x834F764A;     // EVENT_CALCULATE_LOOT: [23] looter, [24] looted entity
        static const Hash kLoot = 0xA5E4EAF7;         // EVENT_LOOT: [26] looter, [29] herb (non-zero = a plant)
        static const Hash kLootDone = 0x52063E5B;     // EVENT_LOOT_COMPLETE: [0] looter, [1] entity, [2] success
        static const Hash kPickup = 0xD7092502;       // EVENT_PICKUP_CARRIABLE: [0] carrier, [2] taken from a horse
        static const Hash kStow = 0x4086BF1A;         // EVENT_PLACE_CARRIABLE_ONTO_PARENT: [0] player, [2] horse
        int n_ev = GET_NUMBER_OF_EVENTS(0);
        for (int i = 0; i < n_ev; ++i) {
            Hash type = GET_EVENT_AT_INDEX(0, i);
            alignas(8) uint64_t d[36] = {};
            auto slot = [&](int k) { return int(uint32_t(d[k])); };
            auto life = [&](const char* what) { ev.push_back({WorldEvent::Life, 0, 1, what}); };
            if (type == kCalmPed) {
                if (!GET_EVENT_DATA(0, i, d, 4) || slot(0) != me) continue;
                LOGD("horse calmed (type %d, fully %d)", slot(2), slot(3));
                ev.push_back({WorldEvent::Horse, 0, slot(2) >= 3 ? 1.0f : 0.7f, "calm"});
            } else if (type == kPrompt) {
                if (!GET_EVENT_DATA(0, i, d, 10) || (slot(0) != 49 && slot(0) != 50)) continue;
                care_ = slot(0) == 49 ? "brush" : "feed";
                care_start_ = s.time;
                care_until_ = s.time + 25;
                LOGD("horse care: %s", care_.c_str());
            } else if (type == kCalcLoot) {
                d[1] = 10;                                 // the two reward arrays' lengths, as Rockstar's scripts set them
                d[12] = 10;
                if (!GET_EVENT_DATA(0, i, d, 26) || slot(23) != me) continue;
                if (GET_IS_ANIMAL(slot(24))) {
                    skin_until_ = s.time + 15;
                    LOGD("skinning");
                }
            } else if (type == kLoot) {
                d[1] = 10;
                d[12] = 10;
                if (GET_EVENT_DATA(0, i, d, 36) && slot(26) == me && slot(29) != 0) life("pluck");
            } else if (type == kLootDone) {
                if (GET_EVENT_DATA(0, i, d, 3) && slot(0) == me) skin_until_ = 0;
            } else if (type == kPickup) {
                if (GET_EVENT_DATA(0, i, d, 4) && slot(0) == me) life("heave");
            } else if (type == kStow) {
                if (GET_EVENT_DATA(0, i, d, 6) && slot(0) == me) life("stow");
            }
        }
    }

    // --- camp life: what Arthur has in his hands, and what he is doing ---
    if (s.time - life_poll_t_ > 0.5) {
        life_poll_t_ = s.time;
        auto running = [](const char* script) { return GET_NUMBER_OF_THREADS_RUNNING_THE_SCRIPT_WITH_THIS_HASH(joaat(script)) > 0; };
        smoking_ = running("generic_smoking_item");
        drinking_ = running("generic_alcohol_item") || running("coffee_drinking");
        eating_ = running("generic_multibite_item") || running("stew_eating");
        bathing_ = running("bathing");
    }
    {
        Hash item = GET_ITEM_INTERACTION_STATE(me);
        std::string kind = item_kind(item);
        if (kind.empty() && item) kind = smoking_ ? "smoke" : drinking_ ? "drink" : eating_ ? "eat" : "";
        if (item != last_item_) {
            if (item) LOGD("item in hand: state 0x%08X (%s)", item, kind.empty() ? "?" : kind.c_str());
            last_item_ = item;
        }
        // each bite, sip or puff: the moment the game applies the item's effect
        static const Hash kApplyStat = 0x1A602839;
        if (kind != "clean" && HAS_ANIM_EVENT_FIRED(me, kApplyStat) && s.time - last_apply_t_ > 0.4) {
            last_apply_t_ = s.time;
            ev.push_back({WorldEvent::Life, 0, 1, kind == "smoke" ? "puff" : kind == "eat" ? "bite" : "gulp"});
        }
        if (kind == "clean") s.activity = "clean_gun";
    }
    if (s.time < care_until_) {                            // each brush stroke / mouthful the horse takes
        static const Hash kInteract = 0x8CED1179;
        if (HAS_ANIM_EVENT_FIRED(me, kInteract) && s.time - last_interact_t_ > 0.3) {
            last_interact_t_ = s.time;
            ev.push_back({WorldEvent::Life, 0, 1, care_});
        }
        if (s.time - care_start_ > 1.5 && !IS_ANIMAL_INTERACTION_RUNNING(me)) care_until_ = 0;
    }
    if (s.time < skin_until_) s.activity = "skin";
    if (bathing_) {
        const char* st = GET_TASK_MOVE_NETWORK_STATE(me);
        std::string b = st ? st : "";
        if (b.rfind("Scrub_", 0) == 0 && b != "Scrub_Idle") {
            s.activity = "scrub";
            s.activity_pan = b.find("Left") != std::string::npos ? -0.6f : b.find("Right") != std::string::npos ? 0.6f : 0.0f;
        }
    }
    {
        static const Hash kCraft[] = {joaat("WORLD_PLAYER_DYNAMIC_KNEEL_FIRE_CRAFT"), joaat("WORLD_PLAYER_DYNAMIC_KNEEL_FIRE_CRAFT_ACTIVE"),
                                      joaat("WORLD_PLAYER_DYNAMIC_KNEEL_FIRE_CRAFT_CUP"), joaat("WORLD_PLAYER_DYNAMIC_KNEEL_KNIFE")};
        static const Hash kCook[] = {joaat("WORLD_PLAYER_DYNAMIC_KNEEL_SEARGRILL1"), joaat("WORLD_PLAYER_DYNAMIC_KNEEL_COOKGRILL1"),
                                     joaat("WORLD_PLAYER_DYNAMIC_KNEEL_COOKGRILL2"), joaat("WORLD_PLAYER_DYNAMIC_KNEEL_COOK_KNIFE_ACTIVE_ARTHUR")};
        Hash sc = GET_ACTIVE_DYNAMIC_SCENARIO(me);
        if (sc) {
            for (Hash h : kCraft) if (sc == h) s.activity = "craft";
            for (Hash h : kCook) if (sc == h) s.activity = "cook";
        }
    }'''),
])

edit("features.h", [("    double next_drop_ = 0, next_thunder_ = 0;",
                     "    double next_drop_ = 0, next_thunder_ = 0, next_texture_ = 0;\n"
                     "    float life_gain_ = 0.6f;\n"
                     "    int texture_n_ = 0;")])
edit("features.cpp", [
    ("    weather_gain_ = c.num(\"Haptics\", \"Weather\", 0.0f);",
     "    weather_gain_ = c.num(\"Haptics\", \"Weather\", 0.0f);\n"
     "    life_gain_ = c.num(\"Haptics\", \"CampLife\", 0.6f);"),
    ("""        } else if (e.type == WorldEvent::Horse) {""",
     """        } else if (e.type == WorldEvent::Life && life_gain_ > 0) {
            static const std::map<std::string, std::string> kCue = {
                {"bite", "bite"}, {"gulp", "gulp"}, {"puff", "puff"}, {"brush", "brush_stroke"}, {"feed", "horse_feed"},
                {"stow", "stow"}, {"heave", "heave"}, {"pluck", "pluck"}};
            auto it = kCue.find(e.cause);
            if (it != kCue.end()) cues.push_back(make(it->second, life_gain_ * e.strength));
        } else if (e.type == WorldEvent::Horse) {"""),
    ("""    if (!g.blocked) {
        if (g.holstering && !was_holstering_ && action_gain_ > 0) {""",
     """    // what Arthur is busy with, felt as a texture while it lasts
    if (!g.blocked && life_gain_ > 0 && !g.activity.empty() && now >= next_texture_) {
        float pan = g.activity_pan;
        std::string cue;
        double gap = 0.5;
        if (g.activity == "clean_gun") { cue = "cloth_rub"; gap = rng_.range(0.4f, 0.6f); pan = (texture_n_ % 2) ? 0.4f : -0.1f; }
        else if (g.activity == "skin") { cue = "skin_cut"; gap = rng_.range(0.55f, 0.9f); pan = 0.3f; }
        else if (g.activity == "scrub") { cue = "scrub"; gap = rng_.range(0.35f, 0.5f); }
        else if (g.activity == "craft") { cue = "craft_tap"; gap = rng_.range(0.8f, 1.5f); pan = 0.2f; }
        else if (g.activity == "cook") { cue = "sizzle"; gap = rng_.range(0.12f, 0.3f); pan = 0.3f; }
        ++texture_n_;
        next_texture_ = now + gap;
        if (!cue.empty()) cues.push_back(make(cue, life_gain_ * rng_.range(0.75f, 1.0f), pan, true));
    }
    if (!g.blocked) {
        if (g.holstering && !was_holstering_ && action_gain_ > 0) {"""),
])
edit("config.cpp", [(
    "TableGames=0.7\n",
    "TableGames=0.7\n"
    "; Camp life: bites, sips and puffs, cleaning your gun, brushing / feeding the horse, skinning, stowing pelts,\n"
    "; picking herbs, bathing, crafting, cooking\n"
    "CampLife=0.6\n")])

# ---------- recipes ----------
hp = REPO / "tools" / "trigger_lab" / "data" / "haptics.json"
txt = hp.read_text(encoding="utf-8").rstrip()
new = {
    "bite": {"_doc": "teeth through food: a crunch and a chew", "gain": 1.0, "layers": [
        {"type": "click", "hz": 240, "cycles": 1, "amp": 0.45, "pan": 0.0},
        {"type": "noise", "lo": 90, "hi": 260, "delay_ms": 10, "decay_ms": 45, "amp": 0.35, "pan": 0.0}]},
    "gulp": {"_doc": "a swallow: a soft low pulse, then a second", "gain": 1.0, "layers": [
        {"type": "tone", "hz": 70, "to_hz": 55, "attack_ms": 25, "decay_ms": 70, "amp": 0.45, "pan": 0.0},
        {"type": "tone", "hz": 65, "to_hz": 50, "delay_ms": 260, "attack_ms": 25, "decay_ms": 70, "amp": 0.35, "pan": 0.0}]},
    "puff": {"_doc": "a long draw on the smoke, swelling", "gain": 1.0, "layers": [
        {"type": "noise", "lo": 40, "hi": 120, "attack_ms": 350, "decay_ms": 250, "amp": 0.3, "pan": 0.0}]},
    "brush_stroke": {"_doc": "the brush drawn along the horse's coat", "gain": 1.0, "layers": [
        {"type": "noise", "lo": 140, "hi": 420, "attack_ms": 60, "decay_ms": 260, "amp": 0.35, "pan": 0.3}]},
    "horse_feed": {"_doc": "the horse's soft lips taking it from your palm", "gain": 1.0, "layers": [
        {"type": "tone", "hz": 55, "attack_ms": 40, "decay_ms": 90, "amp": 0.4, "pan": 0.3},
        {"type": "noise", "lo": 60, "hi": 160, "delay_ms": 120, "decay_ms": 80, "amp": 0.25, "pan": 0.3}]},
    "stow": {"_doc": "a heavy pelt / carcass thrown onto the horse", "gain": 1.0, "layers": [
        {"type": "tone", "hz": 55, "to_hz": 35, "attack_ms": 5, "decay_ms": 160, "amp": 0.85, "pan": 0.0},
        {"type": "noise", "lo": 60, "hi": 200, "decay_ms": 90, "amp": 0.4, "pan": 0.0}]},
    "heave": {"_doc": "lifting something heavy onto the shoulder", "gain": 1.0, "layers": [
        {"type": "tone", "hz": 45, "to_hz": 60, "attack_ms": 250, "decay_ms": 120, "amp": 0.55, "pan": 0.0}]},
    "pluck": {"_doc": "a stem snapping between the fingers", "gain": 1.0, "layers": [
        {"type": "click", "hz": 340, "cycles": 1, "amp": 0.45, "pan": 0.4}]},
    "cloth_rub": {"_doc": "the oiled cloth run along the barrel", "gain": 1.0, "layers": [
        {"type": "noise", "lo": 110, "hi": 330, "attack_ms": 70, "decay_ms": 180, "amp": 0.3, "pan": 0.0}]},
    "skin_cut": {"_doc": "the knife drawn through hide", "gain": 1.0, "layers": [
        {"type": "noise", "lo": 180, "hi": 520, "attack_ms": 40, "decay_ms": 280, "amp": 0.35, "pan": 0.0},
        {"type": "tone", "hz": 90, "to_hz": 70, "attack_ms": 40, "decay_ms": 240, "amp": 0.2, "pan": 0.0}]},
    "scrub": {"_doc": "the scrub brush on skin", "gain": 1.0, "layers": [
        {"type": "noise", "lo": 160, "hi": 450, "attack_ms": 40, "decay_ms": 160, "amp": 0.3, "pan": 0.0}]},
    "craft_tap": {"_doc": "small work in the hands: a tap, a twist", "gain": 1.0, "layers": [
        {"type": "click", "hz": 250, "cycles": 1, "amp": 0.35, "pan": 0.0},
        {"type": "noise", "lo": 100, "hi": 300, "delay_ms": 60, "decay_ms": 50, "amp": 0.2, "pan": 0.0}]},
    "sizzle": {"_doc": "meat spitting over the fire, felt through the stick", "gain": 1.0, "layers": [
        {"type": "click", "hz": 400, "cycles": 1, "amp": 0.18, "pan": 0.0}]},
}
d = json.loads(txt)
added = [k for k in new if k not in d]
if added:
    body = ",\n".join(f'  "{k}": ' + json.dumps(new[k]) for k in added)
    txt = txt[:-1].rstrip() + ",\n" + body + "\n}\n"
    json.loads(txt)
    hp.write_text(txt, encoding="utf-8")
print("patched; recipes added:", added)
