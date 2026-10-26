#!/usr/bin/env python3
"""Build the in-game "DualSense" settings PAGE (a real page of the pause menu's Settings UI).

Usage: build_dualsense_page.py [--oodle] [xml_base_dir] [mod_dir]
  xml_base_dir default: third_party/downloads/rdr2_ui/xml   (game XML, output of rbf2xml.py --batch)
  mod_dir      default: mod/lml/DualSenseRDR2
  --oodle      store our two files Oodle-compressed (needed: the game crashes on an uncompressed new scene)

Produces (in mod_dir):
  xml/data/ui/startup_data/settings/flow/settings_group_flow.ymt   flow, XML (game file + our edits)
  xml/data/ui/startup_data/settings/screens/dualsense_page.ymt     our new scene, XML
  data/ui/startup_data/settings/...                                 the same two as binary RBF
  diff/settings_group_flow.ymt.diff                                 our flow edits vs the game file
  replace/update_4/x64/data/ui/startup_data.rpf                     update_4.rpf/x64/data/ui/startup_data.rpf
        with settings/flow/settings_group_flow.ymt replaced and settings/screens/dualsense_page.ymt ADDED

How the page works (no script runs while the pause menu is open):
  * Settings > Controls > "DualSense" (controls.ymt, transition "dualsense_settings") follows the link
    "dualsense_settings" of state settings_main in settings_group_flow -> our states:
        settings_main.dualsense_page_resources   rage__StateResourceLoader (streams our scene)
          .dualsense_page                        StateUIObjectStreamedSceneHost, same ParentPath /
                                                 animations as input_mappings_flow's scene; "back" -> settings_main
  * Our scene draws like a Settings page: the pause background, a pause_title template, divider rules,
    the focused row's description on the left and the rows on the right, all in one 1920x1080 panel in a
    viewbox inside a safeframe_ui_main_screen panel (a copied settings grid drew nothing). Element names
    must not repeat settings/screens/main.ymt's (its focus-lost animation hides them by name).
  * Each row is an instance of the game's own stepper template (boot_flow/hdr/list_item_int_stepper or
    list_item_option_stepper, streamed by settings_launcher_flow for the HDR screen) whose data context
    is ScriptDatastoreRoot.DualSenseSettings.<row> (uiBindingContextBehavior, as hdr_calibration.ymt).
    The template binds value TWO-WAY, so left/right changes the data store while scripts are frozen.
  * Texts: label keys only - the .asi adds the texts to the game's string table (text_inject.cpp).

Data store contract (the .asi creates it BEFORE the pause menu opens and reads it back after;
settings_ui.cpp page_sync):
  ScriptDatastoreRoot.DualSenseSettings.<row>   container with
      value (int, two-way; option rows: index), enabled, visible (bool), prompt (string),
      minimum, maximum, step (int)               int stepper rows
      options (hash array of text labels)        option stepper rows
"""
import difflib
import os
import sys
import uuid
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dualsense_settings as settings  # noqa: E402
import rbf2xml  # noqa: E402
import rpf8  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC_ARCHIVE = "update_4.rpf"
INNER = "x64/data/ui/startup_data.rpf"

FLOW_REL = "x64/data/ui/startup_data/settings/flow/settings_group_flow.ymt"
FLOW_ARC = "settings/flow/settings_group_flow.ymt"
FLOW_OUT = "data/ui/startup_data/settings/flow/settings_group_flow.ymt"
SCENE_NAME = "settings/screens/dualsense_page"          # SceneName / archive path without extension
SCENE_ARC = SCENE_NAME + ".ymt"
SCENE_OUT = "data/ui/startup_data/settings/screens/dualsense_page.ymt"
HEADER_NAME = "settings/widgets/dualsense_list_header"  # our group header template (streamed by our state)
HEADER_ID = "dualsense_list_header"
HEADER_ARC = HEADER_NAME + ".ymt"
HEADER_OUT = "data/ui/startup_data/" + HEADER_ARC
PERCENT_NAME = "settings/widgets/dualsense_percent_stepper"  # number stepper with "%" (streamed by our state)
PERCENT_ID = "dualsense_percent_stepper"
PERCENT_ARC = PERCENT_NAME + ".ymt"
PERCENT_OUT = "data/ui/startup_data/" + PERCENT_ARC
PERCENT_SRC = "x64/data/ui/startup_data/boot_flow/hdr/list_item_int_stepper.ymt"   # the game's, as the base

TRANSITION = "dualsense_settings"                        # <transition> of the row in controls.ymt
STORE = "DualSenseSettings"                              # ScriptDatastoreRoot.<STORE>
TITLE_LABEL = "DUALSENSE_SETTINGS"                       # "DualSense" (dualsense_settings.ENTRY_LABELS)
PAGE_HOST = ("MV_SETTINGS_HOST.PAUSEMENU_PAGE_HOST_ANIM.PAUSEMENU_PAGE_HOST.GRD_SETTINGS_GRID."
             "PAN_SETTINGS_PAGE_HOST")

# ---------------------------------------------------------------- the rows
# The list (and its texts) is dualsense_settings.ROWS - the .asi is built from the same list (settings_rows.inc).
ROWS = settings.ROWS


def guid(name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "dualsense-rdr2/" + name))


def x(s):
    return escape(str(s))


# ---------------------------------------------------------------- XML snippets
def layout(h="HALIGN_STRETCH", v="VALIGN_STRETCH", w=None, ht=None, extra=""):
    p = ["<horizontalAlignment>%s</horizontalAlignment>" % h,
         "<verticalAlignment>%s</verticalAlignment>" % v,
         "<widthContentMode>%s</widthContentMode>" % ("CONTENT_MODE_RAW" if w is not None else "CONTENT_MODE_AUTO"),
         "<heightContentMode>%s</heightContentMode>" % ("CONTENT_MODE_RAW" if ht is not None else "CONTENT_MODE_AUTO")]
    if w is not None:
        p.append('<width value="%d"/>' % w)
    if ht is not None:
        p.append('<height value="%d"/>' % ht)
    return ('<UseLayoutEngine value="true"/><LayoutParams type="rage__LayoutParamInstanceAsset"><params>'
            + "".join(p) + extra + "</params></LayoutParams>")


STRETCH_FILL = ('<Item type="rage__SpecializedParamInstanceAsset"><params type="rage__fwuiStretchParams">'
                '<Stretch>FILL</Stretch></params></Item>')


def text_item(name, style, static, lay, bindings="", extra=""):
    """UIText. static = ("label", GXT) -> <Text>, ("raw", s) -> <RawText>, None."""
    s = ""
    if static is not None:
        kind, val = static
        s = "<Text>%s</Text>" % x(val) if kind == "label" else "<RawText>%s</RawText>" % x(val)
    mb = "<MemberBindings>%s</MemberBindings>" % bindings if bindings else ""
    return ('<Item type="UIText"><Name>%s</Name>%s<Style>%s</Style>%s%s%s</Item>'
            % (name, s, style, extra, lay, mb))


def visible_when_ready(ready=True):
    """Visible <- ScriptDatastoreRoot.DualSenseSettings.ready == 1 (or != 1). The .asi creates it together with
    the values - not on the title screen, where no mod script runs."""
    return ('<MemberBindings><Item><MemberName>Visible</MemberName><Setup><Path>ScriptDatastoreRoot.%s.ready</Path>'
            '<PathType>PATH_ABSOLUTE</PathType></Setup><Converter type="rage__fwuiBoolValueConversion">%s'
            '<TargetValue type="rage__fwuiValueInt"><value value="1"/></TargetValue><Operator>EQUAL</Operator>'
            '</Converter></Item></MemberBindings>' % (STORE, '' if ready else '<Invert value="true"/>'))


def row_name(row):
    return "ROW_" + row["id"]


def stepper(row):
    """One row: a stepper template with its data context in our data store (as hdr_calibration.ymt binds its
    steppers to hdr_calibration.<setting>): levels = our percent stepper, the rest the game's option stepper."""
    typ = PERCENT_ID if row["kind"] == "level" else "list_item_option_stepper"
    return ('<Item type="UITemplateInstancingItem"><NameOverride>%s</NameOverride><Type>%s</Type>'
            '<Properties><Item type="SF_String"><Name>Label</Name><Value>%s</Value></Item></Properties>'
            '<Behaviors><Item type="uiBindingContextBehavior"><Context><Path><pathElements>'
            '<Item>ScriptDatastoreRoot</Item><Item>%s</Item><Item>%s</Item></pathElements></Path>'
            '<PathType>PATH_ABSOLUTE</PathType></Context></Item></Behaviors></Item>'
            % (row_name(row), typ, settings.label_key(row), STORE, row["id"]))


def header_template_xml():
    """Group title between the rows, looking like the game's settings_group_item.ymt. Our own template: the
    game's hdr_menu_sub_header showed only its first instance in a list (its root element has a name; the
    stepper templates, which repeat fine, have none)."""
    body = ('<UIPanel>%s<Children><Item type="UIText"><Name>TXT_Header</Name><Style>PAUSE_TEXT_SUB_HEADER</Style>'
            '<VAlign>CENTER</VAlign>%s</Item></Children></UIPanel>'
            % (layout("HALIGN_STRETCH", "VALIGN_TOP", None, 54), layout("HALIGN_CENTER", "VALIGN_CENTER", None, 54)))
    return rbf2xml.to_xml(rbf2xml.from_xml('<?xml version="1.0" encoding="UTF-8"?>\n' + body))


PERCENT_ANCHOR = """        <Item type="UIPanel">
          <Name>PAN_RightArrow</Name>"""


def percent_template_xml(game_xml):
    """The game's list_item_int_stepper (HDR screen: d-pad steps, left stick adjusts smoothly) with a "%"
    text after the number. Same data context fields: value (two-way), minimum, maximum, step, prompt..."""
    assert game_xml.count(PERCENT_ANCHOR) == 1, "list_item_int_stepper layout changed (game update?)"
    pct = ('<Item type="UIText"><Name>TXT_Percent</Name><RawText>%%</RawText>%s<HAlign>CENTER</HAlign>'
           '<VAlign>CENTER</VAlign><ParagraphStyle>SINGLELINE</ParagraphStyle><Style>MENU_TEXT_BODY</Style>'
           '<AutoSize>SHRINK_TO_FIT_TEXTFIELD</AutoSize></Item>' % layout("HALIGN_RIGHT", "VALIGN_CENTER"))
    # through the RBF model so it is formatted like the rest
    pct_xml = rbf2xml.to_xml(rbf2xml.from_xml('<?xml version="1.0" encoding="UTF-8"?>\n<Wrap>%s</Wrap>' % pct))
    pct_xml = "".join("      " + line + "\n" for line in pct_xml.splitlines()[2:-1])
    i = game_xml.index(PERCENT_ANCHOR)
    return game_xml[:i] + pct_xml + game_xml[i:]


def header(row):
    key = settings.label_key(row)
    return ('<Item type="UITemplateInstancingItem"><NameOverride>%s</NameOverride><Type>%s</Type>'
            '<Properties><Item type="SF_String"><Name>Label</Name><Value>%s</Value></Item></Properties></Item>'
            % (key, HEADER_ID, key))


def options_list(lay, special=""):
    """settings_list_inner.ymt CurrentSettings: the headers and steppers, one flat list (the navigation of the
    scroll viewer finds no row nested deeper)."""
    items = "".join(header(r) if r["kind"] == "header" else stepper(r) for r in ROWS)
    return ('<Item type="UIStackPanel"><Name>SP_OptionsList</Name>%s<SpecializedLayoutParams>'
            '<Item type="rage__SpecializedParamInstanceAsset"><params type="rage__StackPanelParams">'
            '<orientation>PANEL_ORIENT_VERTICAL</orientation></params></Item>%s</SpecializedLayoutParams>'
            '<BehaviorSet><Behaviors><Item type="uiDisplayObjectBehavior"><SymbolName>fcContainer</SymbolName></Item>'
            '</Behaviors></BehaviorSet><Instancing>%s</Instancing></Item>' % (lay, special, items))


def row_path(row):
    """The row's stepper, from SV_List."""
    return "SP_OptionsList." + row_name(row)


# Page geometry in 1920x1080 units (measured on the game's Settings > Controls page). A grid copied from
# settings/screens/main.ymt drew nothing at all, so everything sits in one panel placed by margins.
LEFT_X, LEFT_W = 98, 428          # title / description column
LIST_X, LIST_W = 854, 970         # rows column
TOP_RULE_Y, BOTTOM_RULE_Y = 116, 964


def at(x, y, w=None, h=None):
    return layout("HALIGN_LEFT", "VALIGN_TOP", w, h, '<leftMargin value="%d"/><topMargin value="%d"/>' % (x, y))


def rule(name, x, y, w):
    return ('<Item type="UIImage"><Name>%s</Name><Color>COLOR_WHITE</Color><TextureDictionary>pausemenu_settings_startup'
            '</TextureDictionary><Texture>DIVIDER_LINE_SHORT</Texture>%s<SpecializedLayoutParams>%s'
            '</SpecializedLayoutParams></Item>' % (name, at(x, y, w, 4), STRETCH_FILL))


def title():
    """pause_title (store/widgets/title, streamed by settings_launcher_flow) scaled into the title box."""
    return ('<Item type="UIViewbox"><Name>VB_Title</Name>%s<SpecializedLayoutParams>'
            '<Item type="rage__SpecializedParamInstanceAsset"><params type="rage__ViewboxParams">'
            '<stretchDirection>STRETCH_DIRECTION_BOTH</stretchDirection><stretchType>STRETCH_TYPE_UNIFORM</stretchType>'
            '</params></Item></SpecializedLayoutParams><Instancing><Item type="UITemplateInstancingItem">'
            '<Type>pause_title</Type><Properties><Item type="SF_String"><Name>primaryTitle</Name><Value>%s</Value>'
            '</Item><Item type="SF_Bool"><Name>dividerVisible</Name><Value value="false"/></Item></Properties></Item>'
            '</Instancing></Item>' % (at(LEFT_X, 52, None, 56), TITLE_LABEL))


def descriptions():
    """Left column: the focused row's description, each text shown while its row has focus."""
    kids = []
    for row in ROWS:
        if row["kind"] == "header" or not row["desc"]:
            continue
        # from TXT_Desc_<id>: ^ = itself, ^.^ = PAN_Desc, ^.^.^ = PAN_Page
        focused = ('<Item><MemberName>Visible</MemberName><Setup><Path>^.^.^.SV_List.%s.focusable.Focused'
                   '</Path><PathType>PATH_LOCAL</PathType></Setup></Item>' % row_path(row))
        kids.append(text_item("TXT_Desc_" + row["id"], "PAUSE_TEXT_BODY", ("label", settings.desc_key(row)),
                              layout("HALIGN_STRETCH", "VALIGN_TOP"), focused,
                              '<IsRichText value="true"/><AutoSize>NONE</AutoSize><Visible value="false"/>'))
    return ('<Item type="UIPanel"><Name>PAN_Desc</Name>%s<Visible value="false"/>%s<Children>%s</Children></Item>'
            % (at(LEFT_X, TOP_RULE_Y + 16, LEFT_W, BOTTOM_RULE_Y - TOP_RULE_Y - 32), visible_when_ready(),
               "".join(kids)))


def rows_list():
    """Right column: settings_list_inner.ymt's scroll viewer - its navigation behaviour keeps the focused row
    in view."""
    return ('<Item type="UIScrollViewer"><Name>SV_List</Name><ScrollBoundryBegin value="1"/><ScrollBoundryEnd value="1"/>'
            '<EnableAdornmentMask value="true"/>%s<SpecializedLayoutParams>'
            '<Item type="rage__SpecializedParamInstanceAsset"><params type="rage__ScrollViewerParams">'
            '<scrollContents value="true"/><scrollHorizontally value="false"/>'
            '<vScrollBarVisibility>SCROLLBAR_VISIBILITY_AUTO</vScrollBarVisibility></params></Item>'
            '</SpecializedLayoutParams><BehaviorSet><Behaviors><Item type="uiScreenNavigationBehavior">'
            '<Name>navigation</Name><NavData><Flags>NAV_FLAGS_WRAPPING_Y</Flags></NavData></Item></Behaviors>'
            '</BehaviorSet><Visible value="false"/>%s<Children>%s</Children></Item>'
            % (at(LIST_X, TOP_RULE_Y + 6, LIST_W, BOTTOM_RULE_Y - TOP_RULE_Y - 12), visible_when_ready(),
               options_list(layout("HALIGN_STRETCH", "VALIGN_TOP"))))


def not_ready():
    """Instead of empty rows (title screen): where to change the settings."""
    return ('<Item type="UIText"><Name>TXT_NotReady</Name><Text>%s</Text><Style>PAUSE_TEXT_BODY</Style>'
            '<HAlign>CENTER</HAlign><VAlign>CENTER</VAlign>%s%s</Item>'
            % (settings.NOT_READY_KEY, at(LIST_X, (TOP_RULE_Y + BOTTOM_RULE_Y) // 2 - 60, LIST_W, 120),
               visible_when_ready(False)))


def scene_xml():
    page_panel = ('<Item type="UIPanel"><Name>PAN_Page</Name>%s<Children>%s%s%s%s%s%s%s%s</Children></Item>'
                  % (layout("HALIGN_CENTER", "VALIGN_CENTER", 1920, 1080), title(),
                     rule("IMG_TitleRule", LEFT_X, TOP_RULE_Y, LEFT_W), rule("IMG_DescFooterRule", LEFT_X, BOTTOM_RULE_Y, LEFT_W),
                     rule("IMG_ListHeaderRule", LIST_X, TOP_RULE_Y, LIST_W),
                     rule("IMG_ListFooterRule", LIST_X, BOTTOM_RULE_Y, LIST_W), descriptions(), rows_list(),
                     not_ready()))
    viewbox = ('<Item type="UIViewbox"><Name>VB_Page</Name>%s<SpecializedLayoutParams>'
               '<Item type="rage__SpecializedParamInstanceAsset"><params type="rage__ViewboxParams">'
               '<stretchDirection>STRETCH_DIRECTION_BOTH</stretchDirection><stretchType>STRETCH_TYPE_UNIFORM'
               '</stretchType></params></Item></SpecializedLayoutParams><Children>%s</Children></Item>'
               % (layout(), page_panel))
    # our names must differ from settings/screens/main.ymt's: that page shares PAN_SETTINGS_PAGE_HOST with ours
    # and its focus-lost animation hides "PANSettingsMain" / "IMG_PauseBackgroundMain" - ours too (blank page)
    background = ('<Item type="UIImage"><Name>IMG_DualSenseBackground</Name><TextureDictionary>pm_background_startup'
                  '</TextureDictionary><Texture>PAUSE_BACKGROUND</Texture><LayoutAttachmentOverride>safeframe_main_screen'
                  '</LayoutAttachmentOverride>%s<SpecializedLayoutParams>%s</SpecializedLayoutParams></Item>'
                  % (layout(), STRETCH_FILL))
    main = ('<Item type="UIPanel"><Name>PAN_DualSenseMain</Name><UseLayoutEngine value="true"/>'
            '<LayoutAttachmentOverride>safeframe_ui_main_screen</LayoutAttachmentOverride>'
            '<LayoutParams type="rage__LayoutParamInstanceAsset"><params><horizontalAlignment>HALIGN_STRETCH'
            '</horizontalAlignment><verticalAlignment>VALIGN_STRETCH</verticalAlignment><widthContentMode>'
            'CONTENT_MODE_AUTO</widthContentMode><heightContentMode>CONTENT_MODE_AUTO</heightContentMode></params>'
            '</LayoutParams><Children>%s</Children></Item>' % viewbox)
    behaviors = ('<Item type="uiFeedbackContextBehavior"><ContextType>SETTINGS_MENU_CONFIG</ContextType>'
                 '<RequiresFocus value="false"/></Item>'
                 '<Item type="uiScreenBehavior"><Screen><ID>dualsense_settings</ID><ModalMouseFocus value="true"/>'
                 '</Screen></Item>'
                 '<Item type="uiScreenHotkeyBehavior"><Name>backHotkey</Name><FlowOp><Link>back</Link></FlowOp>'
                 '<Message>fwuiInputMessageBack</Message><HintText>IB_BACK</HintText></Item>')
    body = ('<UIPanel><Name>PAUSE_SETTINGS_DUALSENSE_PAGE</Name>%s<BehaviorSet><Behaviors>%s</Behaviors>'
            '</BehaviorSet><Children>%s%s</Children></UIPanel>' % (layout(), behaviors, background, main))
    # pretty-print through the RBF model (also validates the XML)
    return rbf2xml.to_xml(rbf2xml.from_xml('<?xml version="1.0" encoding="UTF-8"?>\n' + body))


# ---------------------------------------------------------------- flow edits
FLOW_LINK_ANCHOR = """              <Item key="to_benchmark">
                <Target>benchmark_check_unapplied_changes</Target>
                <LinkType type="rage__fwuiLinkTypeForward"/>
              </Item>
            </LinkMap>"""

FLOW_LINK_NEW = """              <Item key="%s">
                <Target>dualsense_page_resources.dualsense_page</Target>
                <LinkType type="rage__fwuiLinkTypeForward"/>
              </Item>
""" % TRANSITION

FLOW_STATE_ANCHOR = """              <Item>
                <ID>restorePrevious</ID>"""

# pattern: input_mappings_flow.ymt (ResourceLoader with UIObjectSceneStreamingDependencyResource, then the
# scene host in PAN_SETTINGS_PAGE_HOST with Enter/Exit animations); "back" like gamepad_map/restoreDefaults.
FLOW_STATE_NEW = """              <Item>
                <ID>dualsense_page_resources</ID>
                <State type="rage__StateResourceLoader">
                  <Resources>
                    <Item type="UITemplateStreamingDependencyResource">
                      <Name>%(header)s</Name>
                      <Template>
                        <Id>%(header_id)s</Id>
                        <PropertyKeys>
                          <Item key="Label">
                            <Target>
                              <PathType>PATH_LOCAL</PathType>
                              <Path>TXT_Header</Path>
                            </Target>
                            <Property>Text</Property>
                          </Item>
                        </PropertyKeys>
                      </Template>
                    </Item>
                    <Item type="UITemplateStreamingDependencyResource">
                      <Name>%(percent)s</Name>
                      <Template>
                        <Id>%(percent_id)s</Id>
                        <PropertyKeys>
                          <Item key="Label">
                            <Target>
                              <PathType>PATH_LOCAL</PathType>
                              <Path>TXT_LeftLabel</Path>
                            </Target>
                            <Property>Text</Property>
                          </Item>
                        </PropertyKeys>
                      </Template>
                    </Item>
                    <Item type="UIObjectSceneStreamingDependencyResource">
                      <Name>%(scene)s</Name>
                    </Item>
                  </Resources>
                </State>
                <Children>
                  <Item>
                    <ID>dualsense_page</ID>
                    <State type="StateUIObjectStreamedSceneHost">
                      <ParentPath>%(host)s</ParentPath>
                      <HideSceneOnAttachment value="true"/>
                      <EnterAnimation>pausemenu_submenu_enter</EnterAnimation>
                      <ExitAnimation>pausemenu_submenu_exit</ExitAnimation>
                      <GCOnRemove value="true"/>
                      <SceneName>%(scene)s</SceneName>
                    </State>
                    <LinkMap>
                      <Item key="back">
                        <Target>^.^</Target>
                        <LinkType type="rage__fwuiLinkTypeBackward"/>
                      </Item>
                    </LinkMap>
                    <Guid>%(g2)s</Guid>
                  </Item>
                </Children>
                <Guid>%(g1)s</Guid>
              </Item>
""" % dict(scene=SCENE_NAME, host=PAGE_HOST, header=HEADER_NAME, header_id=HEADER_ID, percent=PERCENT_NAME,
           percent_id=PERCENT_ID,
           g1=guid("dualsense_page_resources"), g2=guid("dualsense_page"))


def edit_flow(src):
    assert src.count(FLOW_LINK_ANCHOR) == 1, "settings_group_flow LinkMap anchor not found (game update?)"
    assert src.count(FLOW_STATE_ANCHOR) == 1, "settings_group_flow restorePrevious anchor not found"
    assert TRANSITION not in src
    i = src.index(FLOW_LINK_ANCHOR) + len(FLOW_LINK_ANCHOR) - len("            </LinkMap>")
    src = src[:i] + FLOW_LINK_NEW + src[i:]
    i = src.index(FLOW_STATE_ANCHOR)
    return src[:i] + FLOW_STATE_NEW + src[i:]


# ---------------------------------------------------------------- build
def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "w" if isinstance(data, str) else "wb"
    kw = dict(encoding="utf-8", newline="\n") if isinstance(data, str) else {}
    with open(path, mode, **kw) as fh:
        fh.write(data)


def to_rbf(xml_text):
    rbf = rbf2xml.xml_to_rbf_bytes(xml_text)
    back = rbf2xml.rbf_bytes_to_xml(rbf)
    assert rbf2xml.xml_to_rbf_bytes(back) == rbf, "RBF round trip not stable"
    assert back == rbf2xml.to_xml(rbf2xml.from_xml(xml_text)), "RBF does not decode to the same XML"
    return rbf


def verify(orig, built_path, replaced, added):
    """orig: original archive; replaced: {hash: bytes}; added: {path: bytes}."""
    new = rpf8.RPF8(built_path)
    assert new.tag == 0xFF and new.count == orig.count + len(added)
    hs = [e.hash for e in new.entries]
    assert hs == sorted(hs) and len(set(hs)) == len(hs), "TOC not sorted / duplicate hash"
    # data ranges: inside the body, after the TOC, no overlaps
    body_end = new.length - new.names_len
    assert new.names_len == orig.names_len and new.names_blob == orig.names_blob
    rng = sorted((e.offset, e.offset + e.disk_size) for e in new.entries)
    assert rng[0][0] >= 0x110 + 24 * new.count
    assert all(a[1] <= b[0] for a, b in zip(rng, rng[1:])) and rng[-1][1] <= body_end
    moved = 0
    for a in orig.entries:
        b = rpf8.lookup_hash(new, a.hash)
        assert b is not None and b.ext_id == a.ext_id
        if a.hash in replaced:
            assert new.read_entry(b) == replaced[a.hash], "replaced entry 0x%08X differs" % a.hash
            continue
        assert (a.v1, a.v3) == (b.v1, b.v3), "TOC changed for 0x%08X" % a.hash
        if a.v2 != b.v2:
            moved += 1
            assert (a.v2 & ~(0x7FFFFFFF << 28)) == (b.v2 & ~(0x7FFFFFFF << 28)), "only the offset may change"
        assert new.read_entry(b) == orig.read_entry(a), "entry 0x%08X differs" % a.hash
    for path, data in added.items():
        h, eid = rpf8.path_hash(path)
        b = rpf8.lookup_hash(new, h)
        assert b is not None and b.ext_id == eid and not b.is_resource and b.key_id == 0xFF
        assert new.read_entry(b) == data, "added entry %s differs" % path
        assert rpf8.find_entry(new, path)[2].hash == h
    return new, moved


def main(argv):
    oodle = "--oodle" in argv
    argv = [a for a in argv if a != "--oodle"]
    base = argv[0] if argv else os.path.join(REPO, "third_party", "downloads", "rdr2_ui", "xml")
    out = argv[1] if len(argv) > 1 else os.path.join(REPO, "mod", "lml", "DualSenseRDR2")

    with open(os.path.join(base, FLOW_REL), encoding="utf-8") as fh:
        flow_orig = fh.read()
    flow_new = edit_flow(flow_orig)
    scene = scene_xml()
    header = header_template_xml()
    with open(os.path.join(base, PERCENT_SRC), encoding="utf-8") as fh:
        percent = percent_template_xml(fh.read())
    flow_rbf, scene_rbf, header_rbf = to_rbf(flow_new), to_rbf(scene), to_rbf(header)
    percent_rbf = to_rbf(percent)

    write(os.path.join(out, "xml", FLOW_OUT), flow_new)
    write(os.path.join(out, "xml", SCENE_OUT), scene)
    write(os.path.join(out, FLOW_OUT), flow_rbf)
    write(os.path.join(out, SCENE_OUT), scene_rbf)
    write(os.path.join(out, "xml", HEADER_OUT), header)
    write(os.path.join(out, HEADER_OUT), header_rbf)
    write(os.path.join(out, "xml", PERCENT_OUT), percent)
    write(os.path.join(out, PERCENT_OUT), percent_rbf)
    write(os.path.join(out, "diff", "settings_group_flow.ymt.diff"),
          "".join(difflib.unified_diff(flow_orig.splitlines(True), flow_new.splitlines(True),
                                       "a/" + FLOW_REL, "b/" + FLOW_REL, n=3)))
    print("flow  %s: XML %d, RBF %d bytes" % (FLOW_OUT, len(flow_new), len(flow_rbf)))
    print("scene %s: XML %d, RBF %d bytes" % (SCENE_OUT, len(scene), len(scene_rbf)))

    # archive
    rpf8.NAMES.load()
    rpf8.NAMES.add(SCENE_NAME)
    rpf8.NAMES.add(HEADER_NAME)
    rpf8.NAMES.add(PERCENT_NAME)
    top = rpf8.RPF8(os.path.join(rpf8.GAME_DIR, SRC_ARCHIVE))
    ent = next(e for e in top.entries if e.display_name().lower() == INNER)
    sub = top.nested(ent)
    fh_, _ = rpf8.path_hash(FLOW_ARC)
    fidx = next(i for i, e in enumerate(sub.entries) if e.hash == fh_)
    wrap = (lambda d: (d, "oodle")) if oodle else (lambda d: d)
    added = {SCENE_ARC: scene_rbf, HEADER_ARC: header_rbf, PERCENT_ARC: percent_rbf}
    built = rpf8.rebuild_archive(sub, {fidx: wrap(flow_rbf)}, {k: wrap(v) for k, v in added.items()})
    rpf_out = os.path.join(out, "replace", "update_4", "x64", "data", "ui", "startup_data.rpf")
    write(rpf_out, built)
    new, moved = verify(sub, rpf_out, {fh_: flow_rbf}, added)
    sh, _ = rpf8.path_hash(SCENE_ARC)
    print("archive %s: %d -> %d entries, %d -> %d bytes, %d entries moved for the larger TOC; "
          "replaced %s (0x%08X), added %s (0x%08X, TOC index %d)%s; verified OK"
          % (rpf_out, sub.count, new.count, sub.length, len(built), moved, FLOW_ARC, fh_, SCENE_ARC, sh,
             [e.hash for e in new.entries].index(sh), " [oodle]" if oodle else ""))

    print("\npage rows (data store ScriptDatastoreRoot.%s.<id>, filled by the .asi from settings_rows.inc):" % STORE)
    for r in ROWS:
        if r["kind"] == "header":
            print("  -- %s" % r["text"])
        else:
            print("  %-22s %-8s %s.%s  options %s" % (r["id"], r["kind"], r["section"], r["key"],
                                                    ", ".join(settings.option_keys(r))))


if __name__ == "__main__":
    main(sys.argv[1:])
