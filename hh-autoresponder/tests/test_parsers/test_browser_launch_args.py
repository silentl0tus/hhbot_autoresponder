import ast
from pathlib import Path

from app.utils.browser import _LAUNCH_ARGS


def test_browser_manager_launch_args_contain_sandbox_and_gpu():
    assert "--no-sandbox" in _LAUNCH_ARGS
    assert "--disable-gpu" in _LAUNCH_ARGS


def test_all_chromium_launch_calls_have_required_args():
    """Verify that every playwright chromium.launch call across the codebase
    includes '--no-sandbox' and '--disable-gpu'."""
    repo_root = Path(__file__).resolve().parents[2]
    python_files = list(repo_root.glob("app/**/*.py")) + [
        repo_root / "manual_login.py",
        repo_root / "manual_login_max.py",
        repo_root / "scripts/inspect_sofi.py",
    ]

    checked_calls = 0
    for path in python_files:
        if not path.exists():
            continue
        code = path.read_text(encoding="utf-8")
        if "chromium.launch" not in code:
            continue

        tree = ast.parse(code, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # Look for xxx.chromium.launch(...)
                if isinstance(func, ast.Attribute) and func.attr == "launch":
                    checked_calls += 1
                    # Find 'args' keyword or parameter
                    args_kw = next((kw for kw in node.keywords if kw.arg == "args"), None)
                    assert args_kw is not None, f"{path}:{node.lineno} chromium.launch() is missing 'args' parameter"

                    # If args is a variable or list, verify in AST or source
                    if isinstance(args_kw.value, ast.List):
                        literals = [elt.value for elt in args_kw.value.elts if isinstance(elt, ast.Constant)]
                        assert "--no-sandbox" in literals, f"{path} missing --no-sandbox"
                        assert "--disable-gpu" in literals, f"{path} missing --disable-gpu"
                    elif isinstance(args_kw.value, ast.Name):
                        # Passed as variable name, e.g. launch_args or _LAUNCH_ARGS
                        # Check that the variable defined in file contains required flags
                        assert "--no-sandbox" in code, f"{path} missing --no-sandbox"
                        assert "--disable-gpu" in code, f"{path} missing --disable-gpu"

    assert checked_calls >= 5, f"Expected at least 5 launch calls checked, got {checked_calls}"
