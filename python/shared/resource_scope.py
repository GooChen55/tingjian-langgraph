"""Names owned by this project on a shared development VM.

Keep naming checks independent of clients so maintenance commands and applications
use exactly the same boundary. There is deliberately no arbitrary prefix option.
"""
import re
from dataclasses import dataclass

OWNER = "aillisten-dev/v1"
SCHEMAS = {
    **{f"tingshu_{module}": f"aillisten_dev_{module}" for module in
       ("account", "album", "dispatch", "live", "order", "payment", "system", "user")},
    "listening_ops": "aillisten_dev_ops",
}


@dataclass(frozen=True)
class ResourceScope:
    mysql_user: str = "aillisten_dev_app"
    mysql_reader: str = "aillisten_dev_reader"
    redis_user: str = "aillisten_dev_app"
    redis_prefix: str = "aillisten:dev:"
    rabbit_vhost: str = "/aillisten-dev"
    rabbit_user: str = "aillisten_dev_app"
    nacos_namespace: str = "aillisten-dev"
    nacos_group: str = "AILLISTEN_DEV"

    def schema(self, legacy: str) -> str:
        if legacy not in SCHEMAS:
            raise ValueError("Database is not in the project resource manifest")
        return SCHEMAS[legacy]

    def es_index(self, kind: str) -> str:
        if kind not in {"albums", "metadata", "knowledge"}:
            raise ValueError("Unknown project index")
        return f"aillisten-dev-{kind}-v2" if kind == "albums" else f"aillisten-dev-{kind}-v1"

    def assert_es_index(self, name: str) -> None:
        if name not in {self.es_index(k) for k in ("albums", "metadata", "knowledge")}:
            raise ValueError("Refusing to access an index outside this project")


SCOPE = ResourceScope()


def remap_schemas(source: str) -> str:
    """Render an isolated copy; never edit versioned SQL migration files."""
    pattern = r"\b(" + "|".join(re.escape(k) for k in SCHEMAS) + r")\b"
    return re.sub(pattern, lambda match: SCHEMAS[match[0]], source)


def sql_statements(source: str):
    """Split MySQL dumps without breaking quoted text or executable comments."""
    start = i = 0
    quote = None
    comment = None
    while i < len(source):
        ch = source[i]
        nxt = source[i:i + 2]
        if comment:
            if comment == "line" and ch == "\n":
                comment = None
            elif comment == "block" and nxt == "*/":
                comment = None
                i += 1
        elif quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                if i + 1 < len(source) and source[i + 1] == quote:
                    i += 1
                else:
                    quote = None
        elif ch in "'\"`":
            quote = ch
        elif nxt == "/*":
            comment = "block"
            i += 1
        elif ch == "#" or (nxt == "--" and
                               (i + 2 == len(source) or source[i + 2].isspace())):
            comment = "line"
        elif ch == ";":
            value = source[start:i].strip()
            if value:
                yield value
            start = i + 1
        i += 1
    if quote or comment == "block":
        raise ValueError("Unterminated SQL literal or comment")
    rest = source[start:].strip()
    if rest and re.sub(r"--[^\n]*|#[^\n]*|/\*(?!\!)[\s\S]*?\*/", "", rest).strip():
        yield rest
