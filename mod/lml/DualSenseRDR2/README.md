# DualSenseRDR2 – LML package: the "DualSense" page in the game's Settings

Adds Settings > Controls > Controller > **DualSense**: a real page of the game's settings menu that lists
every setting of the mod (adaptive triggers, haptics, microphone, lightbar, speaker, gyro). The game's own
UI changes the values while the menu is open; `DualSenseRDR2.asi` keeps them in step with
`DualSenseRDR2.ini` (it fills the page's data store while you play and saves what the page changed as
soon as the menu closes).

## Files and where they go (Lenny's Mod Loader)
| package file | copy to (game folder) | what it is |
|---|---|---|
| `install.xml` + `data/ui/settings/controls.ymt` | `lml/DualSenseRDR2/` | the "DualSense" row in Settings > Controls (gamepad page) |
| `replace/update_4/x64/data/ui/startup_data.rpf` | `lml/replace/update_4/x64/data/ui/startup_data.rpf` | the page: flow states, the page scene, the group header widget |
| `replace/update_3/x64/data/lang/american_rel.rpf` | `lml/replace/update_3/x64/data/lang/american_rel.rpf` | the page's English texts (added to `settings.yldb`) |

LML can't replace single files inside nested archives, so the two archives are whole rebuilt copies of
the game's own (`addonDLC:/replace/...` in vfs.log = the `lml` folder). Their new entries must be
Oodle-compressed - the game crashes on an uncompressed new scene.

## Building (after a game update: rebuild all, the edits are rebased on the new game files)
Game XML first: `extract_ui.py` + `rbf2xml.py --batch` into `third_party/downloads/rdr2_ui/xml`. Then:

    python -I tools/rpf8/dualsense_settings.py         # the list -> mod/src/settings_rows.inc (rebuild the .asi)
    python -I tools/rpf8/make_lml_dualsense.py          # the Settings row (controls.ymt)
    python -I tools/rpf8/build_dualsense_page.py --oodle  # the page -> startup_data.rpf
    python -I tools/rpf8/build_lang.py                  # the texts -> american_rel.rpf

The settings themselves are listed once, in `tools/rpf8/dualsense_settings.py`; the page, its texts and
the .asi's `SettingsMenu` are all generated from that list.

## Contents
| file | purpose |
|---|---|
| `data/...` | the binary (RBF) files: controls.ymt, settings_group_flow.ymt, the page scene, the header widget |
| `xml/...` | the same files as plain XML |
| `diff/...` | our edits of the two game files (controls.ymt, settings_group_flow.ymt) |

## How the page works (findings)
- The row's `transition` "dualsense_settings" is a link of state `settings_main` in
  `settings/flow/settings_group_flow.ymt`; it leads to our states: a resource loader (streams the scene and
  the header widget) with a scene host in `PAN_SETTINGS_PAGE_HOST`, like `input_mappings_flow`.
- Every row is the game's own `list_item_option_stepper` template (streamed for the HDR screen) whose
  data context is `ScriptDatastoreRoot.DualSenseSettings.<row id>`: `value` (two-way: the UI writes it),
  `options` (a hash array of text labels), `prompt`, `enabled`, `visible`.
- No script runs while the pause menu is open - the binding does the work; the .asi reads the values back
  afterwards.
- Pitfalls met on the way: element names equal to those of `settings/screens/main.ymt` get hidden by its
  focus-lost animation (blank page); a grid copied from that page drew nothing; the navigation behaviour
  only finds rows one stack panel deep; repeated `hdr_menu_sub_header` instances showed only once (hence
  our own header widget); a string table grown to a size that isn't one power-of-two page
  (0x11000) makes the game quit silently when Settings opens.
