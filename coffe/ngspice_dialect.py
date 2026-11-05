# Co-Nexus: what COFFE's HSPICE decks need beyond hatf-tech's generic foreign-deck rules to run
# on ngspice. Two COFFE habits HSPICE accepts and ngspice (even with ngbehavior=hsa) does not:
#
# 1. bare_rc_param: an R, C or L whose value is a parameter name ("CWIRE_1 n_in gnd Cw").
#    ngspice reads the name as a model; braces make it an expression ("{Cw}"). Applied to the
#    libraries COFFE writes (basic_subcircuits.l, ...), which are copied to <name>.ngspice.l
#    beside the originals; includes.ngspice.l points at the copies.
# 2. port_probe: a measure that probes a subcircuit port by hierarchical name
#    ("V(Xload_1.Xtile_1.Xsb_mux_on_out.n_in)"). HSPICE resolves a port to the net it is
#    connected to; ngspice only knows nets by the scope that owns them. Hierarchy resolves each
#    such path, walking up through the instances, to the owning net's ngspice name.
#
# 3. source_param: a parameter name among the arguments of a source function
#    ("VIN n_in gnd PULSE (supply_v 0 3n 0 0 2n 4n)"); ngspice rejects it as the first value.
#    Braces again ("PULSE ({supply_v} 0 ...)"), in the deck and the libraries.
#
# 4. tran_tmax: ".TRAN 1p 8n" gives ngspice a maximum time step of 1 ps (it caps the step at the
#    print step); HSPICE's step control is not tied to it. A maximum step (COFFE_NGSPICE_TMAX,
#    default 5p) is appended: on sb_mux 5 times faster, delays within 0.1 % of the 1 ps run (20p:
#    16 times, within 1 %).
#
# 5. ground_find: ".MEASURE TRAN x FIND V(gnd) AT=3n" (COFFE's carry-chain decks); ngspice keeps no vector for
#    ground, so the measure fails, and COFFE's sizing treats a failed logic-low voltage as an invalid point. It
#    becomes ".MEASURE TRAN x PARAM='0'": the value HSPICE reports for ground.
#
# All are logged as named rules (rule, count), like hatf-tech's RuleApplied, for the run record.

import os
import re

## Library files COFFE's includes.l pulls in; sweep_data.l is the per-point include and is left alone.
SWEEP_INCLUDE = "sweep_data.l"
## Suffix of the translated copies.
SUFFIX = ".ngspice.l"
## Suffix of the includes copy without the sweep include, for decks that run points in parallel (each includes its own values).
POINTS_SUFFIX = ".ngspice.points.l"

_BARE_RC = re.compile(r"(?im)^(\s*[rcl]\w*\s+[\w.!#]+\s+[\w.!#]+\s+)([a-z_]\w*)(\s*(?:[$;].*)?)$")
_LIB_REF = re.compile(r"""(?im)^(\s*\.(?:lib|include|inc)\s+)(["']?)([^"'\s]+)(\2)""")
_PROBE = re.compile(r"(?<![\w.])([vV])\(\s*([\w.]+)\s*(?:,\s*([\w.]+)\s*)?\)")
_SOURCE_FN = re.compile(r"(?im)^(\s*[vi]\w*\s+.*?\b(?:pulse|pwl|sin|exp|sffm)\s*\()([^)]*)(\))")
_TRAN = re.compile(r"(?im)^(\s*\.tran\s+(?!sweep)\S+\s+(?!sweep)\S+)((?:\s+sweep\b.*)?)\s*$")
_GROUND_FIND = re.compile(r"(?im)^(\s*\.meas(?:ure)?\s+tran\s+\w+)\s+find\s+v\(\s*(?:gnd|0)\s*\)\s+at\s*=\s*\S+\s*$")
_GROUND = {"0", "gnd", "gnd!"}


def logical_lines(text):
    """ The deck's lines with '+' continuations joined and comments ('*' lines, '$' tails) dropped. """

    lines = []
    for raw in text.replace("\r", "").splitlines():
        line = raw.split("$")[0].rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            continue
        if stripped.startswith("+") and lines:
            lines[-1] += " " + stripped[1:].strip()
        else:
            lines.append(stripped)
    return lines


def _nodes_and_name(tokens):
    """ Split an X or .SUBCKT line's tokens (after its own name) into nodes and the last name, dropping params. """

    words = []
    for i, token in enumerate(tokens):
        if "=" in token or (i + 1 < len(tokens) and tokens[i + 1].startswith("=")):
            break
        words.append(token)
    return words


class Hierarchy(object):
    """ Subcircuit definitions and instances of a deck and its libraries, to resolve hierarchical node names. """

    def __init__(self, texts):

        # subckt name -> (ports, {instance name -> (nodes, subckt name)}); "" is the top level.
        self.subckts = {"": ([], {})}
        scope = ""
        for text in texts:
            for line in logical_lines(text):
                tokens = line.split()
                head = tokens[0].lower()
                if head == ".subckt":
                    words = _nodes_and_name(tokens[1:])
                    scope = words[0].lower()
                    self.subckts[scope] = ([w.lower() for w in words[1:]], {})
                elif head in (".ends", ".eom"):
                    scope = ""
                elif head.startswith("x"):
                    words = _nodes_and_name(tokens[1:])
                    if words:
                        self.subckts.setdefault(scope, ([], {}))[1][head] = ([w.lower() for w in words[:-1]], words[-1].lower())
        return


    def resolve(self, path):
        """ The ngspice name of the net a hierarchical path ("Xa.Xb.node") reaches, or the path (lowercased) when it cannot tell. """

        parts = path.lower().split(".")
        node, instances = parts[-1], parts[:-1]
        # Subckt of each instance on the path, from the top.
        chain, scope = [], ""
        for name in instances:
            entry = self.subckts.get(scope, ([], {}))[1].get(name)
            if entry is None:
                return path.lower()
            chain.append((name, entry[0], entry[1]))
            scope = entry[1]
        # Walk up while the node is a port of the innermost subckt.
        while chain and node not in _GROUND:
            name, connections, subckt = chain[-1]
            ports = self.subckts.get(subckt, ([], {}))[0]
            if node not in ports or ports.index(node) >= len(connections):
                break
            node = connections[ports.index(node)]
            chain.pop()
        if node in _GROUND:
            return "0"
        return ".".join([c[0] for c in chain] + [node])


def translate_library(text):
    """ Brace bare R/C/L parameter values; returns the text and how many changed. """

    return _BARE_RC.subn(r"\1{\2}\3", text)


def translate_library_rules(text):
    """ Every library rule; returns the text and {rule: count}. """

    text, rc = translate_library(text)
    text, sources = brace_source_params(text)
    return text, {"bare_rc_param": rc, "source_param": sources}


def brace_source_params(text):
    """ Brace bare parameter names among source-function arguments; returns the text and how many changed. """

    count = [0]

    def arguments(match):
        tokens = []
        for token in match.group(2).split():
            if re.match(r"^[a-z_]\w*$", token, re.I):
                token = "{" + token + "}"
                count[0] += 1
            tokens.append(token)
        return match.group(1) + " ".join(tokens) + match.group(3)

    return _SOURCE_FN.sub(arguments, text), count[0]


def tran_tmax(text, tmax):
    """ Give a two-argument .TRAN a maximum time step ("0 <tmax>"); returns the text and how many changed. """

    if not tmax:
        return text, 0
    return _TRAN.subn(lambda m: m.group(1) + " 0 " + tmax + m.group(2), text)


def ground_find(text):
    """ A FIND of ground's voltage as the constant 0; returns the text and how many changed. """

    return _GROUND_FIND.subn(lambda m: m.group(1) + " PARAM='0'", text)


def resolve_probes(text, hierarchy):
    """ Rewrite V(path) probes that name subcircuit ports to the nets ngspice knows; returns text and count. """

    count = [0]

    def one(path):
        if "." not in path:
            return path
        resolved = hierarchy.resolve(path)
        if resolved != path.lower():
            count[0] += 1
        return resolved

    def replace(match):
        first, second = one(match.group(2)), match.group(3)
        inner = first if second is None else first + ", " + one(second)
        return match.group(1) + "(" + inner + ")"

    return _PROBE.sub(replace, text), count[0]


class CoffeLibraries(object):
    """ ngspice copies of the libraries one includes file pulls in, refreshed when an original changes. With
    translate=False (Spectre, until the probe shows a rule is needed) the libraries are read as COFFE wrote them and
    only the includes are pointed (copies named <name>.<simulator>.l). """

    def __init__(self, includes_path, translate=True, simulator="ngspice"):

        self.translate, self.suffix = translate, "." + simulator + ".l"
        self.points_suffix = "." + simulator + ".points.l"
        self.includes_path = os.path.abspath(includes_path)
        self.folder = os.path.dirname(self.includes_path)
        self._stamp = None
        self.texts = []
        self.rules = {}
        return


    def _sources(self):
        """ The includes file and every library it names (except the sweep include), as absolute paths. """

        with open(self.includes_path) as handle:
            text = handle.read()
        names = [m.group(3) for m in _LIB_REF.finditer(text) if os.path.basename(m.group(3)) != SWEEP_INCLUDE]
        return text, [os.path.join(self.folder, name) for name in names]


    def refresh(self):
        """ Write <name>.ngspice.l copies when an original changed since the last call; returns the includes copy's name. """

        text, sources = self._sources()
        stamp = tuple((path, os.path.getmtime(path), os.path.getsize(path)) for path in [self.includes_path] + sources if os.path.isfile(path))
        target = os.path.basename(self.includes_path)[:-2] + self.suffix
        if stamp == self._stamp:
            return target
        self.texts, self.rules, renamed = [], {"bare_rc_param": 0, "source_param": 0}, {}
        for path in sources:
            if not os.path.isfile(path):
                continue
            with open(path) as handle:
                original = handle.read()
            self.texts.append(original)
            translated, counts = translate_library_rules(original) if self.translate else (original, {})
            if any(counts.values()):
                for rule, count in counts.items():
                    self.rules[rule] += count
                copy = path[:-2] + self.suffix if path.endswith(".l") else path + self.suffix
                with open(copy, "w") as handle:
                    handle.write(translated)
                renamed[os.path.relpath(path, self.folder)] = os.path.relpath(copy, self.folder)

        def point(match):
            return match.group(1) + match.group(2) + renamed.get(match.group(3), match.group(3)) + match.group(4)

        pointed = _LIB_REF.sub(point, text)
        with open(os.path.join(self.folder, target), "w") as handle:
            handle.write(pointed)
        without_sweep = re.sub(r"""(?im)^\s*\.inc(?:lude)?\s+["']?""" + re.escape(SWEEP_INCLUDE) + r"""["']?\s*$""", "* sweep values: each point's deck includes its own", pointed)
        with open(os.path.join(self.folder, os.path.basename(self.includes_path)[:-2] + self.points_suffix), "w") as handle:
            handle.write(without_sweep)
        self._stamp = stamp
        return target


    def deck_for_points(self, deck_text, point_include):
        """ deck_for_ngspice for a deck that runs in its own folder: the libraries by absolute path, without the
        shared sweep include, and the point's values from point_include (next to the deck). Returns text and rules. """

        text, rules = self.deck_for_ngspice(deck_text)
        target = os.path.join(self.folder, os.path.basename(self.includes_path)[:-2] + self.suffix)
        points = os.path.join(self.folder, os.path.basename(self.includes_path)[:-2] + self.points_suffix)
        text = re.sub(r"""(?im)^(\s*\.lib\s+)(["'])[^"']*""" + re.escape(os.path.basename(target)) + r"""\2(.*)$""",
                      lambda m: m.group(1) + m.group(2) + points + m.group(2) + m.group(3) + '\n.INCLUDE "' + point_include + '"', text)
        return text, rules


    def deck_for_ngspice(self, deck_text):
        """ A COFFE deck pointed at the ngspice includes, with its port probes resolved; returns text and rules applied. """

        includes = os.path.basename(self.includes_path)
        target = self.refresh()
        text, pointed = re.subn(r"""(["'])((?:\.\./)*)""" + re.escape(includes) + r"\1", lambda m: m.group(1) + m.group(2) + target + m.group(1), deck_text)
        if not self.translate:
            return text, [("includes", pointed)]
        text, probes = resolve_probes(text, Hierarchy(self.texts + [deck_text]))
        text, rc = translate_library(text)
        text, sources = brace_source_params(text)
        text, tmax = tran_tmax(text, os.environ.get("COFFE_NGSPICE_TMAX", "5p"))
        text, grounds = ground_find(text)
        return text, [
            ("ngspice_includes", pointed), ("bare_rc_param", self.rules.get("bare_rc_param", 0) + rc),
            ("source_param", self.rules.get("source_param", 0) + sources), ("port_probe", probes), ("tran_tmax", tmax), ("ground_find", grounds),
        ]
