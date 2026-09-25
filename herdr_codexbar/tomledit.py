"""Small textual edits to Herdr's config.toml that keep the rest of the file intact.

Only our item in `ui.tab_bar_right`, the `ui.sidebar.agents.rows` value and,
when unset, a few defaults (the sidebar width, the gap between agents) are touched. Everything
else (comments, order, other tab-bar items) stays byte for byte. Configs that
set these through dotted keys or inline tables are refused rather than guessed.
"""

import re
import tomllib

MARKER = "herdr-codexbar"
HEADER = re.compile(r"^[ \t]*\[([^\[\]]+)\][ \t]*(?:#.*)?$", re.M)


class Unsupported(ValueError):
    """The config uses a layout this editor does not rewrite safely."""


def skip_string(text, index):
    """Index just past the TOML string starting at `index`."""
    quote = text[index]
    if text.startswith(quote * 3, index):
        end = text.find(quote * 3, index + 3)
        while quote == '"' and end != -1 and escaped(text, end):
            end = text.find(quote * 3, end + 1)
        if end == -1:
            raise Unsupported("unterminated string")
        end += 3
        while text.startswith(quote, end):  # Up to two quotes may close a multi-line string.
            end += 1
        return end
    index += 1
    while index < len(text) and text[index] != quote and text[index] != "\n":
        index += 2 if quote == '"' and text[index] == "\\" else 1
    if index >= len(text) or text[index] != quote:
        raise Unsupported("unterminated string")
    return index + 1


def escaped(text, index):
    slashes = 0
    while index - slashes - 1 >= 0 and text[index - slashes - 1] == "\\":
        slashes += 1
    return slashes % 2 == 1


def value_end(text, index):
    """Index just past the value starting at `index` (after the `=`), before any comment."""
    depth = 0
    while index < len(text):
        char = text[index]
        if char in "\"'":
            index = skip_string(text, index)
            if depth == 0:
                return index
            continue
        if char == "#":
            if depth == 0:
                return index
            index = text.find("\n", index)
            index = len(text) if index == -1 else index
            continue
        if char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth == 0:
                return index + 1
        elif char == "\n" and depth == 0:
            return index
        index += 1
    return index


def elements(text, start, end):
    """(start, end) of each top-level element of the array spanning text[start:end]."""
    spans, depth, index, begin = [], 0, start + 1, None
    while index < end - 1:
        char = text[index]
        if char in "\"'":
            begin = index if begin is None else begin
            index = skip_string(text, index)
            continue
        if char == "#":
            index = text.find("\n", index, end)
            index = end - 1 if index == -1 else index
            continue
        if char in "[{":
            begin = index if depth == 0 and begin is None else begin
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth == 0:
                spans.append((begin, index + 1))
                begin = None
        elif depth == 0 and not char.isspace() and char != ",":
            begin = index if begin is None else begin
        elif depth == 0 and char == "," and begin is not None:
            spans.append((begin, index))
            begin = None
        index += 1
    if begin is not None:
        spans.append((begin, len(text[:index].rstrip())))
    return spans


def tables(text):
    """[(name, header start, body start, body end)] for each `[table]` header."""
    found = [(match.group(1).strip(), match.start(), match.end()) for match in HEADER.finditer(text)]
    return [(name, start, body, found[i + 1][1] if i + 1 < len(found) else len(text)) for i, (name, start, body) in enumerate(found)]


def normalize_name(name):
    return ".".join(part.strip().strip("\"'") for part in name.split("."))


def find_key(text, table, key):
    """(key line start, value start, value end) of `key` directly in `[table]`, or None."""
    for name, _, body, end in tables(text):
        if normalize_name(name) != table:
            continue
        pattern = re.compile(rf"^[ \t]*{re.escape(key)}[ \t]*=[ \t]*", re.M)
        index = body
        while (match := pattern.search(text, index, end)) is not None:
            # Skip matches inside multi-line values of earlier keys.
            if inside_value(text, body, match.start()):
                index = match.end()
                continue
            return match.start(), match.end(), value_end(text, match.end())
    return None


def inside_value(text, body, position):
    index = body
    key = re.compile(r"^[ \t]*[A-Za-z0-9_\-\"'.]+[ \t]*=[ \t]*", re.M)
    while (match := key.search(text, index, position)) is not None:
        end = value_end(text, match.end())
        if end > position:
            return True
        index = max(end, match.end())
    return False


def table_body(text, table):
    for name, _, body, end in tables(text):
        if normalize_name(name) == table:
            return body, end
    return None


def setup(text, command, rows, defaults):
    """New config text with our tab-bar item, rows and any unset defaults, plus what uninstall needs to undo it.

    `defaults` maps a table name (`ui`, `ui.sidebar.agents`) to its keys and values.
    """
    config = tomllib.loads(text)
    ui = config.get("ui", {})
    previous_rows = None
    added = []

    # --- ui.sidebar.agents.rows
    location = find_key(text, "ui.sidebar.agents", "rows")
    if location:
        _, start, end = location
        previous_rows = text[start:end]
        text = text[:start] + rows + text[end:]
    elif "rows" in ui.get("sidebar", {}).get("agents", {}):
        raise Unsupported("`ui.sidebar.agents.rows` is set with a dotted key or inline table; move it under [ui.sidebar.agents] or edit it by hand")
    elif table_body(text, "ui.sidebar.agents"):
        body, _ = table_body(text, "ui.sidebar.agents")
        text = text[:body] + f"\nrows = {rows}" + text[body:]
    elif "agents" in ui.get("sidebar", {}):
        raise Unsupported("`ui.sidebar.agents` is set with a dotted key or inline table; edit it by hand")
    else:
        text = append(text, f"[ui.sidebar.agents]\nrows = {rows}\n")

    # --- ui.tab_bar_right, directly under [ui]
    item = f"{{ type = \"command\", command = {toml_string(command)}, interval_seconds = 30, timeout_seconds = 2 }}"
    location = find_key(text, "ui", "tab_bar_right")
    if location:
        _, start, end = location
        if not text[start:end].startswith("["):
            raise Unsupported("`ui.tab_bar_right` is not an array")
        text = text[:start] + with_item(text[start:end], item) + text[end:]
    elif "tab_bar_right" in ui:
        raise Unsupported("`ui.tab_bar_right` is set with a dotted key or inline table; move it under [ui] or edit it by hand")
    else:
        text = add_to_ui(text, f"tab_bar_right = [\n  {item},\n]", ui)
    # --- defaults, each inserted right under its table header
    for table, values in defaults.items():
        inserted = []
        for key, value in reversed(values.items()):
            current = tomllib.loads(text)
            for part in table.split("."):
                current = current.get(part, {})
            if key in current:
                continue
            line = f"{key} = {value}  # {MARKER}"
            if table == "ui":
                text = add_to_ui(text, line, ui)
            else:  # The rows above made sure the table has a header.
                body, _ = table_body(text, table)
                text = text[:body] + f"\n{line}" + text[body:]
            inserted.insert(0, key)
        added += inserted

    tomllib.loads(text)  # Never write a config Herdr cannot parse.
    return text, {"rows": previous_rows, "added": added}


def with_item(array, item):
    """The array text with our item replaced, or appended when absent."""
    spans = elements(array, 0, len(array))
    ours = [span for span in spans if MARKER in array[span[0]:span[1]]]
    if ours:
        for span in reversed(ours[1:]):
            array = remove_span(array, *span)
        start, end = ours[0]
        return array[:start] + item + array[end:]
    if not spans:
        return f"[\n  {item},\n]"
    end = spans[-1][1]
    indent = re.search(r"[ \t]*$", array[:spans[-1][0]]).group(0) if "\n" in array[:spans[-1][0]] else " "
    separator = f",\n{indent}" if "\n" in array else ", "
    return array[:end] + separator + item + array[end:]


def remove_span(array, start, end):
    """Drop one element and its separating comma."""
    after = re.match(r"[ \t]*,", array[end:])
    if after:
        end += after.end()
    else:
        before = re.search(r",[ \t]*\n?[ \t]*$", array[:start])
        if before:
            start = before.start()
    line_start = array.rfind("\n", 0, start) + 1
    if not array[line_start:start].strip() and array[end:].startswith("\n"):
        start, end = line_start, end + 1  # Remove the whole line.
    return array[:start] + array[end:]


def add_to_ui(text, line, ui):
    body = table_body(text, "ui")
    if body:
        return text[:body[0]] + f"\n{line}" + text[body[0]:]
    if ui and not any(normalize_name(name).startswith("ui.") for name, *_ in tables(text)):
        raise Unsupported("`ui` is set with a dotted key or inline table; edit it by hand")
    # A [ui] header after its sub-tables is valid TOML as long as [ui] itself was not defined.
    return append(text, f"[ui]\n{line}\n")


def append(text, block):
    return f"{text.rstrip()}\n\n{block}" if text.strip() else block


def uninstall(text, undo):
    """Remove our tab-bar item and the defaults we added, and restore (or remove) the sidebar rows."""
    previous_rows = undo.get("rows")
    for key in undo.get("added", []):
        text = re.sub(rf"^[ \t]*{re.escape(key)}[ \t]*=[^\n#]*# {MARKER}[ \t]*\n?", "", text, flags=re.M)
    location = find_key(text, "ui", "tab_bar_right")
    if location:
        _, start, end = location
        array = text[start:end]
        for span in reversed([span for span in elements(array, 0, len(array)) if MARKER in array[span[0]:span[1]]]):
            array = remove_span(array, *span)
        text = text[:start] + array + text[end:]
    location = find_key(text, "ui.sidebar.agents", "rows")
    if location and "$hc_" in text[location[1]:location[2]]:
        line, start, end = location
        if previous_rows:
            text = text[:start] + previous_rows + text[end:]
        else:
            end = end + 1 if text[end:end + 1] == "\n" else end
            text = text[:line] + text[end:]
    tomllib.loads(text)
    return text


def toml_string(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def is_ours(text):
    """(tab-bar item present, rows are ours)."""
    config = tomllib.loads(text)
    ui = config.get("ui", {})
    items = ui.get("tab_bar_right") or []
    tab = any(MARKER in str(item.get("command", "")) for item in items if isinstance(item, dict))
    rows = "$hc_q1" in str(ui.get("sidebar", {}).get("agents", {}).get("rows", ""))
    return tab, rows
