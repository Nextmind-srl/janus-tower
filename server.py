"""
GCP AI Cost & Governance Control Tower - Modular Server Entrypoint & Assembler.
Loads modular backend packages from backend/*.py and assembles frontend/{css,html,js}/* into index.html.
"""
import base64
import os
import sys

BACKEND_MODULES = [
    "backend/demo_mode.py",  # first: decides the demo switch and the data directory used by config.py
    "backend/config.py",
    "backend/auth_gcp.py",
    "backend/gemini_enterprise.py",
    "backend/gcp_discovery.py",
    "backend/infra_costs.py",
    "backend/infra_costs_minor.py",
    "backend/project_inspector.py",
    "backend/security_posture.py",
    "backend/sync_registry.py",
    "backend/http_routes.py",
]

FRONTEND_CSS_MODULES = [
    "Design/tokens.css",
    "Design/components.css",
    "frontend/css/main.css",
    "Design/jt-theme.css",
]

FRONTEND_HTML_MODULES = [
    "frontend/html/shell_and_views.html",
    "frontend/html/view_gemini_enterprise.html",
    "frontend/html/view_security_and_modals.html",
]

FRONTEND_JS_MODULES = [
    "frontend/js/core_and_auth.js",
    "frontend/js/views_dashboard_and_finops.js",
    "frontend/js/views_pricing.js",
    "frontend/js/gemini_enterprise.js",
    "frontend/js/views_security_and_modals.js",
    "frontend/js/ui_actions.js",
]


def assemble_frontend_html(base_dir: str = None, write_to_disk: bool = True) -> str:
    """Assembles index.html from modular frontend/{css,html,js}/* files."""
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    css_parts = []
    for rel_path in FRONTEND_CSS_MODULES:
        full_p = os.path.join(base_dir, rel_path)
        if not os.path.exists(full_p):
            continue
        with open(full_p, "r", encoding="utf-8") as f:
            css_parts.append(f.read().rstrip())

    html_parts = []
    for rel_path in FRONTEND_HTML_MODULES:
        full_p = os.path.join(base_dir, rel_path)
        if not os.path.exists(full_p):
            continue
        with open(full_p, "r", encoding="utf-8") as f:
            html_parts.append(f.read().rstrip())

    js_parts = []
    for rel_path in FRONTEND_JS_MODULES:
        full_p = os.path.join(base_dir, rel_path)
        if not os.path.exists(full_p):
            continue
        with open(full_p, "r", encoding="utf-8") as f:
            js_parts.append(f.read().rstrip())

    if not css_parts or not html_parts or not js_parts:
        index_path = os.path.join(base_dir, "index.html")
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                return f.read()
        raise RuntimeError("Frontend modules missing and index.html not found.")

    css_block = "\n".join(css_parts)
    html_block = "\n".join(html_parts)
    js_block = "\n\n".join(js_parts)

    assembled = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>JanusTower • Cloud AI Control Tower</title>
  <link rel="icon" href="Design/logos/favicon.svg" type="image/svg+xml" />
  <script src="https://cdn.jsdelivr.net/npm/tailwindcss-cdn@3.4.10/tailwindcss.js" integrity="sha384-cqoPWRPexlPol6Nnsc9Gt050DVIPQMSL4jB2ufKvIBxN7mo6FoC439ixYPCAAPq7" crossorigin="anonymous"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js" integrity="sha384-9nhczxUqK87bcKHh20fSQcTGD4qq5GhayNYSYWqwBkINBhOfQLg/P5HG5lF1urn4" crossorigin="anonymous"></script>
  <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@600&family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&family=Jost:wght@400;500&display=swap" rel="stylesheet">
  <style>
{css_block}
  </style>
</head>
<body class="jt-root h-screen flex flex-col overflow-hidden bg-slate-50 text-slate-800">
{html_block}

  <script>
{js_block}
  </script>
</body>
</html>
"""
    logos_dir = os.path.join(base_dir, "Design", "logos")
    if os.path.isdir(logos_dir):
        for fname in sorted(os.listdir(logos_dir)):
            if fname.endswith(".svg"):
                svg_path = os.path.join(logos_dir, fname)
                if os.path.isfile(svg_path):
                    with open(svg_path, "rb") as svg_f:
                        b64_svg = base64.b64encode(svg_f.read()).decode("ascii")
                    assembled = assembled.replace(
                        f"Design/logos/{fname}",
                        f"data:image/svg+xml;base64,{b64_svg}",
                    )

    if write_to_disk and not getattr(sys, "frozen", False):
        index_path = os.path.join(base_dir, "index.html")
        try:
            existing = ""
            if os.path.exists(index_path):
                with open(index_path, "r", encoding="utf-8") as f:
                    existing = f.read()
            if existing != assembled:
                with open(index_path, "w", encoding="utf-8") as f:
                    f.write(assembled)
        except Exception as e:
            sys.stderr.write(f"[WARN] Unable to update index.html on disk: {e}\n")

    return assembled


def assemble_backend_source(base_dir: str = None) -> str:
    """Concatenates all backend/*.py modules into a single Python source string (for protected .exe builder)."""
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    chunks = []
    for rel_path in BACKEND_MODULES:
        full_p = os.path.join(base_dir, rel_path)
        with open(full_p, "r", encoding="utf-8") as f:
            chunks.append(f"# === MODULE: {rel_path} ===\n" + f.read())
    return "\n\n".join(chunks)


def load_backend_modules(target_globals: dict = None):
    """Loads and executes all modular backend/*.py files in the shared global namespace.

    The backend files are not independent Python modules: they are executed in order
    (BACKEND_MODULES) into ONE namespace, so later files use names defined by earlier
    ones without importing them. Only these fixed, repository-owned files are executed.
    """
    if target_globals is None:
        target_globals = globals()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for rel_path in BACKEND_MODULES:
        full_p = os.path.join(base_dir, rel_path)
        with open(full_p, "r", encoding="utf-8") as f:
            src = f.read()
        code_obj = compile(src, full_p, "exec")
        exec(code_obj, target_globals)  # noqa: S102  # nosec B102 - fixed local source files, see docstring


_DEFER_AUTORUN = True
load_backend_modules(globals())

if __name__ == "__main__":
    if not getattr(sys, "frozen", False):
        assemble_frontend_html(os.path.dirname(os.path.abspath(__file__)), write_to_disk=True)
    run_server()  # noqa: F821 - defined by backend/http_routes.py via load_backend_modules()
