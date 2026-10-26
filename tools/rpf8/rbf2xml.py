#!/usr/bin/env python3
"""RAGE "RBF0" binary XML <-> XML text converter (RDR2 .ymt UI files).

Usage:
  rbf2xml.py <in.ymt> [out.xml]                 RBF -> XML (stdout if no out)
  rbf2xml.py --to-rbf <in.xml> <out.ymt>        XML -> RBF
  rbf2xml.py --batch <rawdir> <xmldir> [--verify]
        convert every RBF0 file under rawdir to xmldir (same relative path, .ymt kept);
        --verify: convert each XML back and compare byte-for-byte with the original.

RBF0 layout (little endian), a pre-order stream of tokens after the 4-byte magic:
  FF FF                      close current element
  FD FF <i32 n> <n bytes>    text payload of current element (UTF-8, NUL terminated;
                             raw binary for content="matrix34" etc.)
  <idx u8> <type u8> [<i16 len> <name>]   node; the name is only present when idx ==
                             number of names defined so far (names table grows in order)
     type 00: element; followed by i16 0, i16 0, i16 attrCount. The next attrCount
              nodes are the element's attributes.
     type 10: u32  | 20: bool true | 30: bool false | 40: f32 | 50: 3 x f32 |
     type 60: i16 len + string (attributes only)
  Non-attribute scalar nodes are XML elements of the form <name value="..."/>
  (<name x= y= z=/> for type 50).

XML mapping rules (also used to infer types when converting XML -> RBF):
  * attributes named value/x/y/z: "true"/"false" -> bool, integer -> u32, decimal -> f32;
    every other attribute is a string.
  * an element with no children/text whose only attribute is a typed `value` (or x,y,z
    floats) becomes a scalar node; everything else is an element.
"""
import os
import re
import struct
import sys
import xml.parsers.expat

import numpy as np

MAGIC = b"RBF0"
TYPED_ATTRS = ("value", "x", "y", "z")
INT_RE = re.compile(r"^[-+]?\d+$")
HEX_RE = re.compile(r"^0[xX][0-9a-fA-F]+$")
FLT_RE = re.compile(r"^[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$|^[-+]?(inf|nan)$")
BINARY_CONTENT = {"matrix34", "matrix44", "float_array", "vector2_array", "vector3_array", "vector4_array"}


class Node:
    __slots__ = ("name", "type", "value", "attrs", "children", "text")

    def __init__(self, name, typ=0, value=None):
        self.name = name
        self.type = typ
        self.value = value
        self.attrs = []      # list of Node (scalar/string)
        self.children = []   # list of Node
        self.text = None     # bytes payload (incl. terminator) or None


# ---------------------------------------------------------------- RBF reading
def read_rbf(data):
    if data[:4] != MAGIC:
        raise ValueError("not RBF0")
    pos = 4
    names = []
    stack = []
    root = None
    cur = None
    pending = []
    n = len(data)
    while pos < n:
        idx = data[pos]
        pos += 1
        if idx == 0xFF:
            if data[pos] != 0xFF:
                raise ValueError("bad close at %d" % pos)
            pos += 1
            if pending[-1]:
                raise ValueError("unprocessed attributes")
            pending.pop()
            cur = stack.pop() if stack else None
            continue
        if idx == 0xFD:
            if data[pos] != 0xFF:
                raise ValueError("bad data token at %d" % pos)
            ln = struct.unpack_from("<i", data, pos + 1)[0]
            pos += 5
            if cur.text is not None or cur.children:
                raise ValueError("mixed content not supported")
            cur.text = bytes(data[pos:pos + ln])
            pos += ln
            continue
        typ = data[pos]
        pos += 1
        if idx == len(names):
            ln = struct.unpack_from("<h", data, pos)[0]
            pos += 2
            names.append(data[pos:pos + ln].decode("latin-1"))
            pos += ln
        elif idx > len(names):
            raise ValueError("bad name index %d at %d" % (idx, pos))
        node = Node(names[idx], typ)
        if typ == 0x00:
            a, b, cnt = struct.unpack_from("<hhh", data, pos)
            if a or b:
                raise ValueError("unexpected element header %d %d" % (a, b))
            pos += 6
        elif typ == 0x10:
            node.value = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        elif typ == 0x20:
            node.value = True
        elif typ == 0x30:
            node.value = False
        elif typ == 0x40:
            node.value = struct.unpack_from("<f", data, pos)[0]
            pos += 4
        elif typ == 0x50:
            node.value = struct.unpack_from("<fff", data, pos)
            pos += 12
        elif typ == 0x60:
            ln = struct.unpack_from("<h", data, pos)[0]
            pos += 2
            node.value = data[pos:pos + ln].decode("utf-8")
            pos += ln
        else:
            raise ValueError("unknown node type 0x%02x at %d" % (typ, pos))
        if cur is not None and pending[-1] > 0:
            pending[-1] -= 1
            cur.attrs.append(node)
            if typ == 0:
                raise ValueError("element used as attribute")
            continue
        if cur is None:
            if root is not None:
                raise ValueError("multiple roots")
            root = node
        else:
            if cur.text is not None:
                raise ValueError("mixed content not supported")
            cur.children.append(node)
        if typ == 0x00:
            if cur is not None:
                stack.append(cur)
            cur = node
            pending.append(cnt)
    if cur is not None or stack:
        raise ValueError("unterminated document")
    return root


# ---------------------------------------------------------------- RBF writing
def write_rbf(root):
    out = bytearray(MAGIC)
    names = {}

    def head(name, typ):
        if name in names:
            out.append(names[name])
            out.append(typ)
        else:
            i = len(names)
            if i >= 0xFD:
                raise ValueError("too many distinct names (>253)")
            names[name] = i
            nb = name.encode("latin-1")
            out.append(i)
            out.append(typ)
            out.extend(struct.pack("<h", len(nb)))
            out.extend(nb)

    def scalar(nd):
        head(nd.name, nd.type)
        t = nd.type
        if t == 0x10:
            out.extend(struct.pack("<I", nd.value & 0xFFFFFFFF))
        elif t in (0x20, 0x30):
            pass
        elif t == 0x40:
            out.extend(struct.pack("<f", nd.value))
        elif t == 0x50:
            out.extend(struct.pack("<fff", *nd.value))
        elif t == 0x60:
            b = nd.value.encode("utf-8")
            out.extend(struct.pack("<h", len(b)))
            out.extend(b)
        else:
            raise ValueError(t)

    def elem(nd):
        if nd.type != 0:
            scalar(nd)
            return
        head(nd.name, 0)
        out.extend(struct.pack("<hhh", 0, 0, len(nd.attrs)))
        for a in nd.attrs:
            scalar(a)
        if nd.text is not None:
            out.extend(b"\xfd\xff")
            out.extend(struct.pack("<i", len(nd.text)))
            out.extend(nd.text)
        for c in nd.children:
            elem(c)
        out.extend(b"\xff\xff")

    elem(root)
    return bytes(out)


# ---------------------------------------------------------------- XML writing
def fmt_float(v):
    f = np.float32(v)
    if np.isnan(f) or np.isinf(f):
        return str(float(f))
    s = np.format_float_positional(f, unique=True, trim="0")
    return s


def fmt_int(v):
    # u32 storage; show negatives (>= 0x80000000) as signed decimal
    return str(v - 0x100000000 if v >= 0x80000000 else v)


def scalar_text(nd):
    t = nd.type
    if t == 0x10:
        return fmt_int(nd.value)
    if t in (0x20, 0x30):
        return "true" if nd.value else "false"
    if t == 0x40:
        return fmt_float(nd.value)
    if t == 0x60:
        return nd.value
    raise ValueError(t)


def esc_text(s):
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\r", "&#13;")
    return s


def esc_attr(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            .replace("\r", "&#13;").replace("\n", "&#10;").replace("\t", "&#9;"))


def text_to_xml(nd):
    """Return XML text for an element's payload."""
    t = nd.text
    content = next((a.value for a in nd.attrs if a.name == "content" and a.type == 0x60), None)
    if content in BINARY_CONTENT and len(t) % 4 == 0 and not (t.endswith(b"\0") and is_text(t[:-1])):
        vals = np.frombuffer(t, dtype="<f4")
        row = 4
        return "\n" + "\n".join(" ".join(fmt_float(x) for x in vals[i:i + row])
                                 for i in range(0, len(vals), row)) + "\n", True
    if not t.endswith(b"\0") or not is_text(t[:-1]):
        raise ValueError("unsupported binary payload in <%s>" % nd.name)
    return esc_text(t[:-1].decode("utf-8")), False


def is_text(b):
    try:
        s = b.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return not any((ord(c) < 0x20 and c not in "\t\n\r") for c in s)


def to_xml(root):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']

    def attrs_str(nd):
        return "".join(' %s="%s"' % (a.name, esc_attr(scalar_text(a))) for a in nd.attrs)

    def rec(nd, ind):
        pad = "  " * ind
        if nd.type == 0x50:
            x, y, z = nd.value
            lines.append('%s<%s x="%s" y="%s" z="%s"/>' % (pad, nd.name, fmt_float(x), fmt_float(y), fmt_float(z)))
            return
        if nd.type != 0:
            lines.append('%s<%s value="%s"/>' % (pad, nd.name, esc_attr(scalar_text(nd))))
            return
        a = attrs_str(nd)
        if nd.text is not None:
            txt, block = text_to_xml(nd)
            if block:
                lines.append("%s<%s%s>" % (pad, nd.name, a))
                lines.extend(pad + "  " + row for row in txt.strip("\n").split("\n"))
                lines.append("%s</%s>" % (pad, nd.name))
            else:
                lines.append("%s<%s%s>%s</%s>" % (pad, nd.name, a, txt, nd.name))
        elif nd.children:
            lines.append("%s<%s%s>" % (pad, nd.name, a))
            for c in nd.children:
                rec(c, ind + 1)
            lines.append("%s</%s>" % (pad, nd.name))
        else:
            lines.append("%s<%s%s/>" % (pad, nd.name, a))

    rec(root, 0)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- XML reading
def typed_attr(name, s):
    n = Node(name)
    if name in TYPED_ATTRS:
        if s in ("true", "false"):
            n.type = 0x20 if s == "true" else 0x30
            n.value = s == "true"
            return n
        if INT_RE.match(s):
            v = int(s)
            if -0x80000000 <= v <= 0xFFFFFFFF:
                n.type, n.value = 0x10, v & 0xFFFFFFFF
                return n
        if HEX_RE.match(s) and int(s, 16) <= 0xFFFFFFFF:
            n.type, n.value = 0x10, int(s, 16)
            return n
        if FLT_RE.match(s):
            n.type, n.value = 0x40, float(np.float32(float(s)))
            return n
    n.type, n.value = 0x60, s
    return n


class _XEl:
    __slots__ = ("tag", "attrib", "kids", "text")

    def __init__(self, tag, attrib):
        self.tag, self.attrib, self.kids, self.text = tag, attrib, [], []


def parse_xml_raw(text):
    """Minimal expat tree builder: no namespace processing (xmlns:* stay ordinary
    attributes, prefixed names stay verbatim), attribute order preserved."""
    p = xml.parsers.expat.ParserCreate()
    p.ordered_attributes = True
    stack = []
    holder = []

    def start(tag, attrs):
        el = _XEl(tag, list(zip(attrs[0::2], attrs[1::2])))
        if stack:
            stack[-1].kids.append(el)
        else:
            holder.append(el)
        stack.append(el)

    def end(tag):
        stack.pop()

    def chars(data):
        if stack:
            stack[-1].text.append(data)

    p.StartElementHandler = start
    p.EndElementHandler = end
    p.CharacterDataHandler = chars
    if isinstance(text, str):
        text = text.lstrip("\ufeff").encode("utf-8")
    p.Parse(text, True)
    return holder[0]


def from_xml(text):
    root = parse_xml_raw(text)

    def rec(el):
        nd = Node(el.tag)
        nd.attrs = [typed_attr(k, v) for k, v in el.attrib]
        kids = el.kids
        txt = "".join(el.text)
        if kids:
            if txt.strip():
                raise ValueError("mixed content in <%s> not supported" % el.tag)
            nd.children = [rec(k) for k in kids]
        elif txt != "":
            content = dict(el.attrib).get("content")
            if content in BINARY_CONTENT and txt.strip() and all(FLT_RE.match(w) for w in txt.split()):
                nd.text = np.array([float(w) for w in txt.split()], dtype="<f4").tobytes()
            else:
                nd.text = txt.encode("utf-8") + b"\0"
        # scalar collapsing
        if not kids and nd.text is None:
            names = [a.name for a in nd.attrs]
            if names == ["value"] and nd.attrs[0].type != 0x60:
                a = nd.attrs[0]
                return Node(nd.name, a.type, a.value)
            if names == ["x", "y", "z"] and all(a.type in (0x40, 0x10) for a in nd.attrs):
                return Node(nd.name, 0x50, tuple(float(np.float32(a.value)) for a in nd.attrs))
        return nd

    return rec(root)


# ---------------------------------------------------------------- CLI
def rbf_bytes_to_xml(data):
    return to_xml(read_rbf(data))


def xml_to_rbf_bytes(text):
    return write_rbf(from_xml(text))


def batch(rawdir, xmldir, verify):
    ok = bad = skipped = 0
    for r, _, fs in os.walk(rawdir):
        for f in fs:
            src = os.path.join(r, f)
            rel = os.path.relpath(src, rawdir)
            with open(src, "rb") as fh:
                data = fh.read()
            if data[:4] != MAGIC:
                skipped += 1
                continue
            try:
                x = rbf_bytes_to_xml(data)
            except Exception as ex:  # noqa
                print("FAIL rbf->xml %s: %s" % (rel, ex))
                bad += 1
                continue
            dst = os.path.join(xmldir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(x)
            if verify:
                try:
                    back = xml_to_rbf_bytes(x)
                except Exception as ex:  # noqa
                    print("FAIL xml->rbf %s: %s" % (rel, ex))
                    bad += 1
                    continue
                if back != data:
                    i = next((k for k in range(min(len(back), len(data))) if back[k] != data[k]), None)
                    print("MISMATCH %s at %s (len %d vs %d)" % (rel, i, len(back), len(data)))
                    bad += 1
                    continue
            ok += 1
    print("converted ok=%d bad=%d skipped(non-RBF)=%d" % (ok, bad, skipped))
    return 1 if bad else 0


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    if argv[0] == "--batch":
        return batch(argv[1], argv[2], "--verify" in argv)
    if argv[0] == "--to-rbf":
        with open(argv[1], encoding="utf-8-sig") as fh:
            b = xml_to_rbf_bytes(fh.read())
        with open(argv[2], "wb") as fh:
            fh.write(b)
        return 0
    with open(argv[0], "rb") as fh:
        x = rbf_bytes_to_xml(fh.read())
    if len(argv) > 1:
        with open(argv[1], "w", encoding="utf-8", newline="\n") as fh:
            fh.write(x)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(x)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
