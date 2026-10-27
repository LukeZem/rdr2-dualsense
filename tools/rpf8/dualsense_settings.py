#!/usr/bin/env python3
"""The mod's settings as shown on the in-game "DualSense" page - the one list everything is built from.

  build_dualsense_page.py   the page (one game stepper per row, sub headers between groups)
  text_inject.cpp (.asi)    the texts (added to the game's loaded string table at run time)
  this script               mod/src/settings_rows.inc (SettingsMenu::entries(); the .asi fills the page's
                            data store from it and writes the page's changes back to the ini) and
                            mod/src/settings_texts.inc (every text of the row and the page; the .asi adds them
                            to the game's loaded string table at run time - any game language)

Usage: dualsense_settings.py      -> writes mod/src/settings_rows.inc and mod/src/settings_texts.inc

Row kinds:
  toggle  ini 0/1          option stepper, options Off / On (the game's own MO_OFF / MO_ON); value = index
  level   ini 0.0 .. max   number stepper in percent (value 0 .. max*100, any whole percent)
  choice  ini one of them  option stepper, options = the given texts (DS_<ID>_<VALUE>); value = index
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
INC = os.path.join(REPO, "mod", "src", "settings_rows.inc")
TEXTS_INC = os.path.join(REPO, "mod", "src", "settings_texts.inc")

# the "DualSense" row in Settings > Controls (make_lml_dualsense.py puts these labels in controls.ymt)
ENTRY_LABELS = {
    "DUALSENSE_SETTINGS": "DualSense",
    "DUALSENSE_SETTINGS_DESC": "Adaptive triggers, haptics, microphone, lightbar and speaker of the DualSense.",
}


def header(text):
    return dict(kind="header", text=text)


def toggle(id, section, key, label, default, desc):
    return dict(kind="toggle", id=id, section=section, key=key, label=label, default=default, desc=desc)


def level(id, section, key, label, default, max, desc):
    return dict(kind="level", id=id, section=section, key=key, label=label, default=default, max=max, desc=desc)


def choice(id, section, key, label, default, choices, desc):
    return dict(kind="choice", id=id, section=section, key=key, label=label, default=default, choices=choices,
                desc=desc)


ROWS = [
    header("Triggers"),
    toggle("triggers_enabled", "Triggers", "Enabled", "Adaptive Triggers", True,
           "Every gun its own pull; fishing line on L2."),
    level("triggers_kick", "Triggers", "KickStrength", "Recoil on the Trigger", 1.0, 2.0,
          "How hard each shot kicks back against your finger."),
    toggle("triggers_cocking", "Triggers", "ManualCocking", "Work the Hammer with R2", True,
           "Single-action guns need their hammer, lever or bolt worked with R2 between shots. "
           "Turn off if you use an automatic cocking mod."),
    header("Haptics"),
    toggle("haptics_enabled", "Haptics", "Enabled", "Haptics", True, "Everything you feel in the grips."),
    level("haptics_strength", "Haptics", "Strength", "Overall Strength", 1.0, 2.0, "Scales every haptic effect."),
    level("haptics_footsteps", "Haptics", "Footsteps", "Footsteps", 0.22, 1.0, "Arthur's steps on the real ground."),
    level("haptics_horse", "Haptics", "Horse", "Hooves", 0.3, 1.0, "Every hoof on the real ground."),
    level("haptics_damage", "Haptics", "Damage", "Taking Hits", 1.0, 2.0, "Hits, felt from the side they came from."),
    level("haptics_gunfire", "Haptics", "Gunfire", "Gunfire Nearby", 0.6, 1.0, "The pressure of other people's shots."),
    level("haptics_camp", "Haptics", "CampLife", "Camp Life", 0.6, 1.0,
          "Eating, drinking, brushing the horse, skinning, bathing..."),
    level("haptics_tables", "Haptics", "TableGames", "Table Games", 0.7, 1.0,
          "Five finger fillet, poker, blackjack, dominoes."),
    level("haptics_rumble", "Haptics", "GameRumble", "Game's Own Rumble", 0.35, 1.0,
          "The game's original vibration, played through the haptics."),
    level("haptics_weather", "Haptics", "Weather", "Rain", 0.0, 1.0, "Rain drops on the hat, as heavy as the rain falls."),
    level("haptics_wheel", "Haptics", "WheelClick", "Weapon Wheel Clicks", 0.6, 1.0,
          "L2 and R2 click like a selector while you browse the weapon wheel."),
    header("Voice and Whistle"),
    toggle("mic_whistle", "Mic", "WhistleForHorse", "Whistle for Your Horse", False,
           "Whistle into the controller's microphone to call your horse."),
    toggle("voice_enabled", "Voice", "Enabled", "Voice Commands", False,
           "Say \"chao\" to greet a stranger and \"easy\" to calm your horse."),
    header("Lightbar and Speaker"),
    toggle("lightbar_enabled", "Lightbar", "Enabled", "Lightbar", True, "Muzzle flash, hits, Dead Eye, honor."),
    level("lightbar_brightness", "Lightbar", "Brightness", "Lightbar Brightness", 1.0, 1.0, ""),
    toggle("lightbar_ammo", "Lightbar", "AmmoLeds", "Rounds on the Player LEDs", True,
           "The player LEDs under the touchpad show the rounds left in the cylinder or magazine."),
    toggle("speaker_mechanics", "Speaker", "Mechanics", "Sounds from the Controller", True,
           "Holster, lasso and mechanism sounds from the controller's speaker."),
    level("speaker_volume", "Speaker", "Volume", "Speaker Volume", 0.35, 1.0, ""),
    header("Experimental"),
    choice("gyro_mode", "Gyro", "Mode", "Gyro Aim", "off", [("off", "Off"), ("aim", "While Aiming")],
           "Small tilt corrections while aiming with L2. Still being tuned."),
]


def label_key(row):
    if row["kind"] == "header":
        return "DS_HDR_" + "".join(c for c in row["text"].upper() if c.isalnum())
    return "DS_" + row["id"].upper()


def desc_key(row):
    return "DS_" + row["id"].upper() + "_DESC"


def choice_key(row, value):
    return "DS_%s_%s" % (row["id"].upper(), value.upper())


def option_keys(row):
    """Text labels of an option stepper's options, index = data store value (levels: none, a number stepper)."""
    if row["kind"] == "toggle":
        return ["MO_OFF", "MO_ON"]
    if row["kind"] == "level":
        return []
    return [choice_key(row, v) for v, _ in row["choices"]]


# the page without values (title screen: no mod script runs there yet)
NOT_READY_KEY = "DS_PAGE_NOT_READY"
NOT_READY_TEXT = "Load your story to change the DualSense settings."


def labels():
    """Every text of the row and the page: {label key: text}."""
    out = dict(ENTRY_LABELS)
    out[NOT_READY_KEY] = NOT_READY_TEXT
    for r in ROWS:
        if r["kind"] == "header":
            out[label_key(r)] = r["text"]
            continue
        out[label_key(r)] = r["label"]
        if r["desc"]:
            out[desc_key(r)] = r["desc"]
        if r["kind"] == "choice":
            for v, text in r["choices"]:
                out[choice_key(r, v)] = text
    return out


def c_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def c_float(v):
    s = "%g" % v
    return s + ("f" if "." in s else ".0f")


def inc_text():
    lines = ["// Generated by tools/rpf8/dualsense_settings.py - edit the list there, then run it and",
             "// build_dualsense_page.py (the in-game page and its texts come from the same list).",
             "// clang-format off"]
    for r in ROWS:
        k = r["kind"]
        if k == "header":
            lines.append("header(%s, %s)," % (c_str(label_key(r)), c_str(r["text"])))
            continue
        common = "%s, %s, %s, %s, %s" % (c_str(r["id"]), c_str(r["section"]), c_str(r["key"]),
                                        c_str(label_key(r)), c_str(r["label"]))
        if k == "toggle":
            lines.append("toggle(%s, %s, %s)," % (common, "true" if r["default"] else "false", c_str(r["desc"])))
        elif k == "level":
            lines.append("level(%s, %s, %s, %s)," % (common, c_float(r["default"]), c_float(r["max"]), c_str(r["desc"])))
        else:
            ch = ", ".join("{%s, %s, %s}" % (c_str(v), c_str(t), c_str(choice_key(r, v))) for v, t in r["choices"])
            lines.append("choice(%s, %s, {%s}, %s)," % (common, c_str(r["default"]), ch, c_str(r["desc"])))
    lines.append("// clang-format on")
    return "\n".join(lines) + "\n"


def texts_inc_text():
    lines = ["// Generated by tools/rpf8/dualsense_settings.py - the texts of the Settings row and the DualSense page",
             "// (label key, English text); text_inject.cpp adds them to the game's string table.",
             "// clang-format off"]
    lines += ["{%s, %s}," % (c_str(k), c_str(v)) for k, v in labels().items()]
    lines.append("// clang-format on")
    return "\n".join(lines) + "\n"


def main():
    ids = [r["id"] for r in ROWS if r["kind"] != "header"]
    assert len(ids) == len(set(ids)), "duplicate row id"
    assert all(i.replace("_", "").isalnum() and i == i.lower() for i in ids)
    with open(INC, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(inc_text())
    with open(TEXTS_INC, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(texts_inc_text())
    print("%s: %d rows, %d headers; %s: %d texts" % (INC, len(ids), len(ROWS) - len(ids), TEXTS_INC, len(labels())))


if __name__ == "__main__":
    main()
