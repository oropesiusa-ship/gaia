"""Filtro AST preventivo; la frontera del SO es el sandbox, no este filtro."""
import ast


class GuardError(ValueError):
    pass


IMPORTS = {"torch", "torch.nn", "torch.nn.functional", "numpy", "math", "dataclasses", "hashlib"}
FROM_IMPORTS = {"torch": {"nn"}, "torch.nn": {"functional"}, "dataclasses": {"dataclass", "asdict"}}
BANNED_NAMES = {"open", "eval", "exec", "compile", "__import__", "globals", "locals", "vars",
                "getattr", "setattr", "delattr", "input", "breakpoint", "exit", "quit", "help"}
BANNED_ATTRS = {"os", "sys", "builtins", "ctypes", "ctypeslib", "lib", "utils", "hub", "jit",
                "serialization", "pickle", "load", "save", "loadtxt", "savetxt", "fromfile", "tofile",
                "memmap", "read", "write", "read_text", "write_text", "read_bytes", "write_bytes",
                "system", "popen", "spawn", "fork", "environ", "getenv", "modules", "import_module",
                "data_ptr", "untyped_storage", "storage", "cudart", "set_device", "set_default_device",
                "set_default_dtype", "set_per_process_memory_fraction", "set_rng_state", "set_rng_state_all",
                "from_file", "genfromtxt", "recfromtxt", "compile", "multiprocessing", "distributed",
                "inspect", "linecache", "package"}


def check_source(source):
    if len(source) > 48000:
        raise GuardError("Candidato excede 48000 caracteres")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise GuardError("Sintaxis inválida: " + str(exc)) from exc
    if not any(isinstance(node, ast.ClassDef) and node.name == "Candidate" for node in tree.body):
        raise GuardError("El protocolo exige una clase Candidate")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name not in IMPORTS for alias in node.names):
                raise GuardError("Import no permitido")
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module not in FROM_IMPORTS or any(a.name not in FROM_IMPORTS[node.module] for a in node.names):
                raise GuardError("Import no permitido")
        elif isinstance(node, ast.Name) and (node.id in BANNED_NAMES or node.id.startswith("__")):
            raise GuardError("Nombre prohibido: " + node.id)
        elif isinstance(node, ast.Attribute):
            allowed_utils = node.attr == "utils" and isinstance(node.value, ast.Attribute) and node.value.attr == "nn"
            super_init = (node.attr == "__init__" and isinstance(node.value, ast.Call)
                          and isinstance(node.value.func, ast.Name) and node.value.func.id == "super"
                          and not node.value.args and not node.value.keywords)
            if (node.attr in BANNED_ATTRS and not allowed_utils) or (
                    node.attr.startswith("_") and node.attr != "_init" and not super_init):
                raise GuardError("Atributo prohibido: " + node.attr)
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                owner = node.value
                while isinstance(owner, ast.Attribute):
                    owner = owner.value
                if not (isinstance(owner, ast.Name) and owner.id == "self"):
                    raise GuardError("No se permite modificar módulos u objetos externos")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            raise GuardError("global/nonlocal no permitido")
    return tree
