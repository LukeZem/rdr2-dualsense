#!/usr/bin/env python3
"""Debug builds of the DualSense settings page: same flow edit, simplified scene.

Usage: page_variant.py <variant> [out_dir]      (out_dir default: build/page_variant/<variant>)
  minimal   root panel (same behaviours) + one big centred text, nothing else
  bg        minimal + the page background image
  probe     several independent elements at different places (see probes())
Builds the Oodle-compressed startup_data.rpf like build_dualsense_page.py --oodle.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_dualsense_page as page  # noqa: E402
import rbf2xml  # noqa: E402

ROOT_BEHAVIORS = ('<Item type="uiFeedbackContextBehavior"><ContextType>SETTINGS_MENU_CONFIG</ContextType>'
                  '<RequiresFocus value="false"/></Item>'
                  '<Item type="uiScreenBehavior"><Screen><ID>dualsense_settings</ID><ModalMouseFocus value="true"/>'
                  '</Screen></Item>'
                  '<Item type="uiScreenHotkeyBehavior"><Name>backHotkey</Name><FlowOp><Link>back</Link></FlowOp>'
                  '<Message>fwuiInputMessageBack</Message><HintText>IB_BACK</HintText></Item>')

BACKGROUND = ('<Item type="UIImage"><Name>IMG_PauseBackgroundMain</Name><TextureDictionary>pm_background_startup'
              '</TextureDictionary><Texture>PAUSE_BACKGROUND</Texture><LayoutAttachmentOverride>safeframe_main_screen'
              '</LayoutAttachmentOverride>%s<SpecializedLayoutParams>%s</SpecializedLayoutParams></Item>'
              % (page.layout(), page.STRETCH_FILL))

HELLO = page.text_item("TXT_Hello", "PAUSE_TEXT_BODY", ("raw", "DUALSENSE TEST PAGE"),
                       page.layout("HALIGN_CENTER", "VALIGN_CENTER"),
                       extra='<ParagraphStyle>SINGLELINE</ParagraphStyle>')


def scene(children):
    body = ('<UIPanel><Name>PAUSE_SETTINGS_DUALSENSE_PAGE</Name>%s<BehaviorSet><Behaviors>%s</Behaviors>'
            '</BehaviorSet><Children>%s</Children></UIPanel>' % (page.layout(), ROOT_BEHAVIORS, children))
    return rbf2xml.to_xml(rbf2xml.from_xml('<?xml version="1.0" encoding="UTF-8"?>\n' + body))


def probe_text(name, text, h, v, extra=""):
    return page.text_item(name, "PAUSE_TEXT_BODY", ("raw", text), page.layout(h, v, extra=extra),
                          extra='<ParagraphStyle>SINGLELINE</ParagraphStyle>')


def probes():
    """Siblings at different places; whatever is missing on screen is what the game refuses to draw."""
    p1 = ('<Item type="UIText"><Name>P1</Name><RawText>P1 text with safeframe attachment</RawText>'
          '<Style>PAUSE_TEXT_BODY</Style><ParagraphStyle>SINGLELINE</ParagraphStyle>'
          '<LayoutAttachmentOverride>safeframe_ui_main_screen</LayoutAttachmentOverride>%s</Item>'
          % page.layout("HALIGN_LEFT", "VALIGN_TOP"))
    p2 = ('<Item type="UIPanel"><Name>P2</Name><UseLayoutEngine value="true"/>'
          '<LayoutAttachmentOverride>safeframe_ui_main_screen</LayoutAttachmentOverride>'
          '<LayoutParams type="rage__LayoutParamInstanceAsset"><params><horizontalAlignment>HALIGN_STRETCH'
          '</horizontalAlignment><verticalAlignment>VALIGN_STRETCH</verticalAlignment><widthContentMode>'
          'CONTENT_MODE_AUTO</widthContentMode><heightContentMode>CONTENT_MODE_AUTO</heightContentMode></params>'
          '</LayoutParams><Children>%s</Children></Item>' % probe_text("P2_Text", "P2 panel with attachment",
                                                                        "HALIGN_RIGHT", "VALIGN_TOP"))
    p3 = ('<Item type="UIViewbox"><Name>P3</Name>%s<SpecializedLayoutParams>'
          '<Item type="rage__SpecializedParamInstanceAsset"><params type="rage__ViewboxParams">'
          '<stretchDirection>STRETCH_DIRECTION_BOTH</stretchDirection><stretchType>STRETCH_TYPE_UNIFORM</stretchType>'
          '</params></Item></SpecializedLayoutParams><Children><Item type="UIPanel"><Name>P3_Panel</Name>%s'
          '<Children>%s</Children></Item></Children></Item>'
          % (page.layout("HALIGN_LEFT", "VALIGN_BOTTOM", 600, 200), page.layout("HALIGN_LEFT", "VALIGN_TOP", 600, 200),
             probe_text("P3_Text", "P3 viewbox", "HALIGN_LEFT", "VALIGN_TOP")))
    p4 = page.options_list(page.layout("HALIGN_LEFT", "VALIGN_CENTER", 900, None, '<leftMargin value="100"/>'))
    p5 = ('<Item type="UIPanel"><Name>P5</Name>%s<Instancing><Item type="UITemplateInstancingItem"><Type>pause_title'
          '</Type><Properties><Item type="SF_String"><Name>primaryTitle</Name><Value>DUALSENSE_SETTINGS</Value></Item>'
          '<Item type="SF_Bool"><Name>dividerVisible</Name><Value value="false"/></Item></Properties></Item>'
          '</Instancing></Item>' % page.layout("HALIGN_CENTER", "VALIGN_TOP", 800, 120))
    return scene(HELLO + p1 + p2 + p3 + p4 + p5)


def scale_probes():
    """Which way of scaling a 1920x1080 panel to the screen draws anything."""
    def page_panel(tag, y):
        txt = page.text_item("TXT_" + tag, "PAUSE_TEXT_BODY", ("raw", tag + " 1920 panel text"),
                             page.at(100, y), extra='<ParagraphStyle>SINGLELINE</ParagraphStyle>')
        return ('<Item type="UIPanel"><Name>PAN_%s</Name>%s<Children>%s</Children></Item>'
                % (tag, page.layout("HALIGN_CENTER", "VALIGN_CENTER", 1920, 1080), txt))

    def viewbox(tag, y, lay, stretch="STRETCH_TYPE_UNIFORM", special=""):
        return ('<Item type="UIViewbox"><Name>VB_%s</Name>%s<SpecializedLayoutParams>%s'
                '<Item type="rage__SpecializedParamInstanceAsset"><params type="rage__ViewboxParams">'
                '<stretchDirection>STRETCH_DIRECTION_BOTH</stretchDirection><stretchType>%s</stretchType>'
                '</params></Item></SpecializedLayoutParams><Children>%s</Children></Item>'
                % (tag, lay, special, stretch, page_panel(tag, y)))

    def attach_panel(tag, child):
        return ('<Item type="UIPanel"><Name>ATT_%s</Name><UseLayoutEngine value="true"/>'
                '<LayoutAttachmentOverride>safeframe_ui_main_screen</LayoutAttachmentOverride>'
                '<LayoutParams type="rage__LayoutParamInstanceAsset"><params><horizontalAlignment>HALIGN_STRETCH'
                '</horizontalAlignment><verticalAlignment>VALIGN_STRETCH</verticalAlignment><widthContentMode>'
                'CONTENT_MODE_AUTO</widthContentMode><heightContentMode>CONTENT_MODE_AUTO</heightContentMode></params>'
                '</LayoutParams><Children>%s</Children></Item>' % (tag, child))

    grid_cell = ('<Item type="rage__SpecializedParamInstanceAsset"><params type="rage__GridChildParams">'
                 '<row value="0"/><column value="0"/></params></Item>')
    q1 = attach_panel("Q1", viewbox("Q1", 100, page.layout()))
    q2 = viewbox("Q2", 300, page.layout())
    q3 = ('<Item type="UIGrid"><Name>GRD_Q3</Name>%s<SpecializedLayoutParams><Item type="rage__SpecializedParamInstanceAsset">'
          '<params type="rage__GridParams"><columns><Item><size value="1"/><type>SIZING_TYPE_STAR</type></Item></columns>'
          '<rows><Item><size value="1"/><type>SIZING_TYPE_STAR</type></Item></rows></params></Item>'
          '</SpecializedLayoutParams><Children>%s</Children></Item>'
          % (page.layout(), viewbox("Q3", 500, page.layout(), special=grid_cell)))
    q4 = attach_panel("Q4", viewbox("Q4", 700, page.layout("HALIGN_CENTER", "VALIGN_STRETCH"),
                                    "STRETCH_TYPE_UNIFORM_TO_FILL"))
    return scene(HELLO + q1 + q2 + q3 + q4)


def part_probes():
    """Each part of the real page in its own scaled panel next to a marker text: a part that kills its
    panel takes the marker with it."""
    def scaled(tag, y, part):
        txt = page.text_item("TXT_" + tag, "PAUSE_TEXT_BODY", ("raw", "%s marker" % tag), page.at(1500, y),
                             extra='<ParagraphStyle>SINGLELINE</ParagraphStyle>')
        pan = ('<Item type="UIPanel"><Name>PAN_Page</Name>%s<Children>%s%s</Children></Item>'
               % (page.layout("HALIGN_CENTER", "VALIGN_CENTER", 1920, 1080), txt, part))
        vb = ('<Item type="UIViewbox"><Name>VB_%s</Name>%s<SpecializedLayoutParams>'
              '<Item type="rage__SpecializedParamInstanceAsset"><params type="rage__ViewboxParams">'
              '<stretchDirection>STRETCH_DIRECTION_BOTH</stretchDirection><stretchType>STRETCH_TYPE_UNIFORM</stretchType>'
              '</params></Item></SpecializedLayoutParams><Children>%s</Children></Item>' % (tag, page.layout(), pan))
        return ('<Item type="UIPanel"><Name>ATT_%s</Name><UseLayoutEngine value="true"/>'
                '<LayoutAttachmentOverride>safeframe_ui_main_screen</LayoutAttachmentOverride>'
                '<LayoutParams type="rage__LayoutParamInstanceAsset"><params><horizontalAlignment>HALIGN_STRETCH'
                '</horizontalAlignment><verticalAlignment>VALIGN_STRETCH</verticalAlignment><widthContentMode>'
                'CONTENT_MODE_AUTO</widthContentMode><heightContentMode>CONTENT_MODE_AUTO</heightContentMode></params>'
                '</LayoutParams><Children>%s</Children></Item>' % (tag, vb))

    return scene(BACKGROUND + HELLO
                 + scaled("R1_title", 60, page.title())
                 + scaled("R2_rule", 250, page.rule("IMG_Rule", page.LEFT_X, 260, page.LEFT_W))
                 + scaled("R3_desc", 400, page.descriptions())
                 + scaled("R4_list", 550, page.rows_list()))


def list_probes():
    """Headers between template steppers, three ways side by side (left / middle / right)."""
    rows = [r for r in page.ROWS if r["kind"] != "header"][:3]
    hdrs = [r for r in page.ROWS if r["kind"] == "header"][:3]

    def hdr(h):
        key = page.settings.label_key(h)
        return ('<Item type="UITemplateInstancingItem"><NameOverride>%s</NameOverride><Type>hdr_menu_sub_header</Type>'
                '<Properties><Item type="SF_String"><Name>Label</Name><Value>%s</Value></Item></Properties></Item>'
                % (key, key))
    items = hdr(hdrs[0]) + page.stepper(rows[0]) + page.stepper(rows[1]) + hdr(hdrs[1]) + page.stepper(rows[2]) + hdr(hdrs[2])
    nav = ('<Item type="uiScreenNavigationBehavior"><Name>navigation</Name><NavData><Flags>NAV_FLAGS_WRAPPING_Y</Flags>'
           '</NavData></Item>')
    fc = '<Item type="uiDisplayObjectBehavior"><SymbolName>fcContainer</SymbolName></Item>'
    stack = lambda name, beh, kids, inst: (  # noqa: E731
        '<Item type="UIStackPanel"><Name>%s</Name>%s<SpecializedLayoutParams><Item type="rage__SpecializedParamInstanceAsset">'
        '<params type="rage__StackPanelParams"><orientation>PANEL_ORIENT_VERTICAL</orientation></params></Item>'
        '</SpecializedLayoutParams><BehaviorSet><Behaviors>%s</Behaviors></BehaviorSet><Children>%s</Children>'
        '<Instancing>%s</Instancing></Item>' % (name, page.layout("HALIGN_STRETCH", "VALIGN_TOP"), beh, kids, inst))
    sv = lambda name, x, beh, child: (  # noqa: E731
        '<Item type="UIScrollViewer"><Name>%s</Name>%s<SpecializedLayoutParams><Item type="rage__SpecializedParamInstanceAsset">'
        '<params type="rage__ScrollViewerParams"><scrollContents value="true"/><scrollHorizontally value="false"/></params>'
        '</Item></SpecializedLayoutParams><BehaviorSet><Behaviors>%s</Behaviors></BehaviorSet><Children>%s</Children></Item>'
        % (name, page.at(x, 150, 560, 700), beh, child))
    static_hdr = page.text_item("TXT_StaticHeader", "PAUSE_TEXT_SUB_HEADER", ("raw", "L3 STATIC HEADER"),
                                page.layout("HALIGN_CENTER", "VALIGN_TOP", None, 54))
    l1 = sv("SV_L1", 40, "", stack("SP_L1", fc + nav, "", items))
    l2 = sv("SV_L2", 680, nav, stack("SP_L2", fc, "", items))
    l3 = sv("SV_L3", 1320, "", stack("SP_L3", fc + nav, static_hdr, page.stepper(rows[0]) + page.stepper(rows[1])))
    marks = "".join(page.text_item("TXT_M%d" % i, "PAUSE_TEXT_BODY", ("raw", t), page.at(x, 100))
                    for i, (t, x) in enumerate([("L1 nav on stack", 40), ("L2 nav on scroll viewer", 680),
                                                ("L3 static + instanced", 1320)]))
    pan = ('<Item type="UIPanel"><Name>PAN_Page</Name>%s<Children>%s%s%s%s</Children></Item>'
           % (page.layout("HALIGN_CENTER", "VALIGN_CENTER", 1920, 1080), marks, l1, l2, l3))
    vb = ('<Item type="UIViewbox"><Name>VB_Page</Name>%s<SpecializedLayoutParams>'
          '<Item type="rage__SpecializedParamInstanceAsset"><params type="rage__ViewboxParams">'
          '<stretchDirection>STRETCH_DIRECTION_BOTH</stretchDirection><stretchType>STRETCH_TYPE_UNIFORM</stretchType>'
          '</params></Item></SpecializedLayoutParams><Children>%s</Children></Item>' % (page.layout(), pan))
    main = ('<Item type="UIPanel"><Name>PAN_Main</Name><UseLayoutEngine value="true"/>'
            '<LayoutAttachmentOverride>safeframe_ui_main_screen</LayoutAttachmentOverride>'
            '<LayoutParams type="rage__LayoutParamInstanceAsset"><params><horizontalAlignment>HALIGN_STRETCH'
            '</horizontalAlignment><verticalAlignment>VALIGN_STRETCH</verticalAlignment><widthContentMode>'
            'CONTENT_MODE_AUTO</widthContentMode><heightContentMode>CONTENT_MODE_AUTO</heightContentMode></params>'
            '</LayoutParams><Children>%s</Children></Item>' % vb)
    return scene(main)


VARIANTS = {
    "lists": list_probes,
    "parts": part_probes,
    "scale": scale_probes,
    "probe": probes,
    "minimal": lambda: scene(HELLO),
    "bg": lambda: scene(BACKGROUND + HELLO),
}

if __name__ == "__main__":
    v = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(page.REPO, "build", "page_variant", v)
    page.scene_xml = VARIANTS[v]
    page.main(["--oodle", os.path.join(page.REPO, "third_party", "downloads", "rdr2_ui", "xml"), out])
