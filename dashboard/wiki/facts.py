"""Keep Markdown infobox tables and queryable facts in sync."""
import re

BOX = re.compile(r'(^:::infobox[^\S\n]*\n)([\s\S]*?)(\n:::(?=\n|$))', re.M)
TABLE = re.compile(r'^\|[^\n]*\|\s*\n\|[ :|\-]+\|[^\S\n]*(?:\n\|[^\n]*\|[^\S\n]*)*', re.M)


def table_facts(content):
    box = BOX.search(content)
    table = TABLE.search(box[2]) if box else None
    if not table: return {}
    facts = {}
    for line in table[0].splitlines()[2:]:
        cells = re.split(r'(?<!\\)\|', line.strip().strip('|'))
        if len(cells) == 2 and cells[0].strip():
            facts[cells[0].strip().replace('\\|', '|')] = cells[1].strip().replace('\\|', '|')
    return facts


def sync_facts(content, metadata, previous=None, rewrite_table=True):
    facts = dict(metadata.get('properties', {}))
    current = table_facts(content)
    old = table_facts(previous) if previous is not None else {}
    box = BOX.search(content)
    has_table = box and TABLE.search(box[2])
    previous_box = BOX.search(previous) if previous is not None else None
    previous_table = TABLE.search(previous_box[2]) if previous_box else None
    table_changed = previous is not None and (
        (has_table.group(0) if has_table else None) !=
        (previous_table.group(0) if previous_table else None))
    if previous is not None and has_table and current != old:
        for key in old.keys() - current.keys(): facts.pop(key, None)
        for key, value in current.items():
            if key not in old and not value and key in facts: continue
            if key not in old or old[key] != value: facts[key] = value
    elif previous is None:
        facts = {**current, **facts}
    metadata = {**metadata, 'properties': facts}
    box = BOX.search(content)
    # Authored Markdown is the source of truth during content edits. Rebuilding
    # from parsed facts discards blank rows, duplicate keys and partial typing.
    # Only explicit property edits to an unchanged table need reconstruction.
    if rewrite_table and not table_changed and box and TABLE.search(box[2]):
        escape = lambda value: str(value).replace('|', '\\|').replace('\n', '<br>')
        table = '| Detail | Value |\n| --- | --- |' + ''.join(f'\n| {escape(k)} | {escape(v)} |' for k,v in facts.items())
        inner = TABLE.sub(lambda _: table, box[2], count=1)
        content = content[:box.start()] + box[1] + inner + box[3] + content[box.end():]
    return content, metadata
