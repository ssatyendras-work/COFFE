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
# All are logged as named rules (rule, count), like hatf-tech's RuleApplied, for the run record.

import os
import re

## Library files COFFE's includes.l pulls in; sweep_data.l is the per-point include and is left alone.
SWEEP_INCLUDE = "sweep_data.l"
## Suffix of the translated copies.
SUFFIX = ".ngspice.l"

_BARE_RC = re.compile(r"(?im)^(\s*[rcl]\w*\s+[\w.!#]+\s+[\w.!#]+\s+)([a-z_]\w*)(\s*(?:[$;].*)?)$")
_LIB_REF = re.compile(r"""(?im)^(\s*\.(?:lib|include|inc)\s+)(["']?)([^"'\s]+)(\2)""")
_PROBE = re.compile(r"(?<![\w.])([vV])\(\s*([\w.]+)\s*(?:,\s*([\w.]+)\s*)?\)")
_SOURCE_FN = re.compile(r"(?im)^(\s*[vi]\w*\s+.*?\b(?:pulse|pwl|sin|exp|sffm)\s*\()([^)]*)(\))")
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
    """ ngspice copies of the libraries one includes file pulls in, refreshed when an original changes. """

    def __init__(self, includes_path):

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
        target = os.path.basename(self.includes_path)[:-2] + SUFFIX
        if stamp == self._stamp:
            return target
        self.texts, self.rules, renamed = [], {"bare_rc_param": 0, "source_param": 0}, {}
        for path in sources:
            if not os.path.isfile(path):
                continue
            with open(path) as handle:
                original = handle.read()
            self.texts.append(original)
            translated, counts = translate_library_rules(original)
            if any(counts.values()):
                for rule, count in counts.items():
                    self.rules[rule] += count
                copy = path[:-2] + SUFFIX if path.endswith(".l") else path + SUFFIX
                with open(copy, "w") as handle:
                    handle.write(translated)
                renamed[os.path.relpath(path, self.folder)] = os.path.relpath(copy, self.folder)

        def point(match):
            return match.group(1) + match.group(2) + renamed.get(match.group(3), match.group(3)) + match.group(4)

        with open(os.path.join(self.folder, target), "w") as handle:
            handle.write(_LIB_REF.sub(point, text))
        self._stamp = stamp
        return target


    def deck_for_ngspice(self, deck_text):
        """ A COFFE deck pointed at the ngspice includes, with its port probes resolved; returns text and rules applied. """

        includes = os.path.basename(self.includes_path)
        target = self.refresh()
        text, pointed = re.subn(r"""(["'])((?:\.\./)*)""" + re.escape(includes) + r"\1", lambda m: m.group(1) + m.group(2) + target + m.group(1), deck_text)
        text, probes = resolve_probes(text, Hierarchy(self.texts + [deck_text]))
        text, rc = translate_library(text)
        text, sources = brace_source_params(text)
        return text, [
            ("ngspice_includes", pointed), ("bare_rc_param", self.rules.get("bare_rc_param", 0) + rc),
            ("source_param", self.rules.get("source_param", 0) + sources), ("port_probe", probes),
        ]
