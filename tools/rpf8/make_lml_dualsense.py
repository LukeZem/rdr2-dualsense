#!/usr/bin/env python3
"""Generate the "DualSense" row of Settings > Controls (the LML loose file controls.ymt).

Usage: make_lml_dualsense.py [xml_base_dir] [out_dir]
  xml_base_dir default: third_party/downloads/rdr2_ui/xml   (output of rbf2xml.py --batch)
  out_dir      default: mod/lml/DualSenseRDR2

One text edit of the game's own (current update_4) x64/data/ui/settings/controls.ymt: a Button item
"dualsense" (transition "dualsense_settings", gamepad page only) right after the "vibration" item. The
transition is followed by our flow states (build_dualsense_page.py), the texts come from LABELS
(the .asi adds them at run time). Writes plain XML (xml/...), binary RBF (data/...) and a unified diff (diff/...).
Re-run after a game update to rebase the edit on the new file.
"""
import difflib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rbf2xml  # noqa: E402
import gxt2  # noqa: E402
import dualsense_settings  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", ".."))

TRANSITION = "dualsense_settings"
LABELS = dualsense_settings.ENTRY_LABELS          # the row's texts (added by the .asi at run time)

CONTROLS_ANCHOR = """          <displayType>kSettingDependency_Hide</displayType>
        </Item>
      </dependencyConditions>
    </Item>
    <Item type="rage__fwuiSettingsItemInfo_Bool">
      <id>photoModeInputEnabled</id>"""

CONTROLS_NEW_ITEM = """    <Item type="rage__fwuiSettingsItemInfo_Bool">
      <id>dualsense</id>
      <displayStyle>kSettingDisplay_Button</displayStyle>
      <displayName>DUALSENSE_SETTINGS</displayName>
      <description>DUALSENSE_SETTINGS_DESC</description>
      <transition>%s</transition>
      <default value="true"/>
      <dependencyConditions>
        <Item platform="x64|ggp">
          <condition type="uiConditionNot">
            <Condition type="uiConditionIsEditingMouseKeyboardSettings"/>
          </condition>
          <displayType>kSettingDependency_Hide</displayType>
        </Item>
      </dependencyConditions>
    </Item>
""" % TRANSITION

def edit_controls(x):
    # insert between the "vibration" item and the "photoModeInputEnabled" item
    assert x.count(CONTROLS_ANCHOR) == 1, "controls.ymt anchor not found (game update?)"
    assert x.index("<id>vibration</id>") < x.index(CONTROLS_ANCHOR)
    i = x.index(CONTROLS_ANCHOR) + x[x.index(CONTROLS_ANCHOR):].index("    <Item type=")
    return x[:i] + CONTROLS_NEW_ITEM + x[i:]


FILES = [
    ("x64/data/ui/settings/controls.ymt", "data/ui/settings/controls.ymt", edit_controls),
]


def write(path, data, text=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if text:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(data)
    else:
        with open(path, "wb") as fh:
            fh.write(data)


def main(base, out):
    for src_rel, dst_rel, fn in FILES:
        with open(os.path.join(base, src_rel), encoding="utf-8") as fh:
            orig = fh.read()
        new = fn(orig)
        rbf = rbf2xml.xml_to_rbf_bytes(new)
        # sanity: RBF -> XML -> RBF stable, and unmodified original still round-trips
        assert rbf2xml.xml_to_rbf_bytes(rbf2xml.rbf_bytes_to_xml(rbf)) == rbf
        write(os.path.join(out, "xml", dst_rel), new, text=True)
        write(os.path.join(out, dst_rel), rbf)
        diff = "".join(difflib.unified_diff(orig.splitlines(True), new.splitlines(True),
                                            "a/" + src_rel, "b/" + src_rel, n=3))
        write(os.path.join(out, "diff", os.path.basename(dst_rel) + ".diff"), diff, text=True)
        print("%s: %d -> RBF %d bytes" % (dst_rel, len(new), len(rbf)))
    print("labels:", ", ".join("%s=0x%08X" % (k, gxt2.label_hash(k)) for k in LABELS))

if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0] if a else os.path.join(REPO, "third_party", "downloads", "rdr2_ui", "xml"),
         a[1] if len(a) > 1 else os.path.join(REPO, "mod", "lml", "DualSenseRDR2"))
