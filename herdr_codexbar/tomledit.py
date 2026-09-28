"""Small textual edits to Herdr's config.toml that keep the rest of the file intact.

Only the `ui.sidebar.agents.rows` value and, when unset, a few defaults (the
sidebar width, the gap between agents) are touched. Everything else (comments,
order, other settings) stays byte for byte. Configs that
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


def setup(text, rows, defaults):
    """New config text with our rows and any unset defaults, plus what uninstall needs to undo it.

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
    """Remove the defaults we added, and restore (or remove) the sidebar rows."""
    previous_rows = undo.get("rows")
    for key in undo.get("added", []):
        text = re.sub(rf"^[ \t]*{re.escape(key)}[ \t]*=[^\n#]*# {MARKER}[ \t]*\n?", "", text, flags=re.M)
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


def rows_are_ours(text):
    rows = tomllib.loads(text).get("ui", {}).get("sidebar", {}).get("agents", {}).get("rows", "")
    return "$hc_q1" in str(rows)


def table_span(text, table):
    """(header start, end) of `[table]`, ending at the next table or array-of-tables header, or None."""
    for name, start, body, _ in tables(text):
        if normalize_name(name) == table:
            following = re.compile(r"^[ \t]*\[", re.M).search(text, body)
            return start, following.start() if following else len(text)
    return None


def set_table(text, table, values):
    """Set `key = value` lines in `[table]`, adding the table at the end when missing; other keys stay."""
    if table_span(text, table) is None:
        *parents, name = table.split(".")
        current = tomllib.loads(text)
        for part in parents:
            current = current.get(part, {})
        if name in current:
            raise Unsupported(f"`{table}` is set with a dotted key or inline table; edit it by hand")
        return append(text, f"[{table}]\n" + "".join(f"{key} = {value}\n" for key, value in values.items()))
    for key, value in reversed(values.items()):
        location = find_key(text, table, key)
        if location:
            _, start, end = location
            text = text[:start] + value + text[end:]
        else:
            body = next(body for name, _, body, _ in tables(text) if normalize_name(name) == table)
            text = text[:body] + f"\n{key} = {value}" + text[body:]
    tomllib.loads(text)
    return text


def remove_table(text, table):
    span = table_span(text, table)
    if span is None:
        return text
    before, after = text[:span[0]].rstrip("\n"), text[span[1]:]
    if not before:
        return after
    return f"{before}\n\n{after}" if after.strip() else f"{before}\n"
