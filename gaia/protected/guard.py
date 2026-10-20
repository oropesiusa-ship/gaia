"""Comprobación estática del código candidato.

IMPORTANTE: esto es un filtro contra errores y abusos evidentes, NO una
frontera de seguridad. La contención CPU real es bwrap obligatorio, namespaces,
bundle de solo lectura y directorio de trabajo privado, además de RLIMIT.
"""
import ast


class GuardError(ValueError):
    pass


ALLOWED_IMPORTS = {"numpy", "math"}
BANNED_NAMES = {"open", "eval", "exec", "compile", "__import__", "globals", "locals",
                "vars", "input", "breakpoint", "getattr", "setattr", "delattr",
                "exit", "quit", "memoryview", "help"}
MAX_CHARS = 24000


def check_source(src):
    if len(src) > MAX_CHARS:
        raise GuardError("código demasiado largo")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        raise GuardError(f"sintaxis: {e}")
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS:
                    raise GuardError(f"import no permitido: {a.name}")
        elif isinstance(n, ast.ImportFrom):
            if (n.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                raise GuardError(f"import no permitido: {n.module}")
        elif isinstance(n, ast.Name) and n.id in BANNED_NAMES:
            raise GuardError(f"nombre prohibido: {n.id}")
        elif isinstance(n, ast.Attribute) and n.attr.startswith("__"):
            raise GuardError(f"atributo prohibido: {n.attr}")
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            raise GuardError("global/nonlocal prohibido")
