import argparse
import asyncio
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from cryptography.fernet import Fernet


def get_project_root() -> Path:
    """Resolve project root directory."""
    return Path(__file__).resolve().parents[4]


def ensure_environment_file(project_root: Path) -> Tuple[bool, str]:
    """
    Ensure .env file exists. If not, create from .env.example with auto-generated encryption key.
    Returns (created_or_updated: bool, message: str).
    """
    env_file = project_root / ".env"
    env_example = project_root / ".env.example"
    fernet_key = Fernet.generate_key().decode()

    if not env_file.exists():
        if env_example.exists():
            content = env_example.read_text(encoding="utf-8")
            if "IGNIS_ENCRYPTION_KEY=" in content:
                content = content.replace("IGNIS_ENCRYPTION_KEY=", f"IGNIS_ENCRYPTION_KEY={fernet_key}")
            else:
                content += f"\nIGNIS_ENCRYPTION_KEY={fernet_key}\n"
            
            if "DATABASE_URL=postgresql://" in content and "DATABASE_URL=sqlite://" not in content:
                content = content.replace(
                    "DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ignis",
                    "DATABASE_URL=sqlite:///ignis.db"
                )
            env_file.write_text(content, encoding="utf-8")
            return True, "Created .env from .env.example with SQLite default & generated Fernet key."
        else:
            default_env = (
                f"DATABASE_URL=sqlite:///ignis.db\n"
                f"DEFAULT_GEO=VN\n"
                f"IGNIS_ENCRYPTION_KEY={fernet_key}\n"
                f"YOUTUBE_API_KEY=\n"
                f"SCHEDULER_INTERVAL_SECONDS=900\n"
            )
            env_file.write_text(default_env, encoding="utf-8")
            return True, "Created minimal .env with SQLite default & generated Fernet key."

    existing_content = env_file.read_text(encoding="utf-8")
    lines = existing_content.splitlines()
    has_key = False
    new_lines = []
    for line in lines:
        if line.startswith("IGNIS_ENCRYPTION_KEY="):
            val = line.split("=", 1)[1].strip()
            if not val:
                line = f"IGNIS_ENCRYPTION_KEY={fernet_key}"
            has_key = True
        new_lines.append(line)
    if not has_key:
        new_lines.append(f"IGNIS_ENCRYPTION_KEY={fernet_key}")
    
    if "\n".join(new_lines) != existing_content:
        env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return True, "Updated existing .env with generated IGNIS_ENCRYPTION_KEY."

    return False, "Existing .env is valid and configured."


async def bootstrap_database() -> Tuple[bool, str]:
    """Initialize SQLite database and verify table schemas."""
    try:
        from ignis.infrastructure.persistence import create_repository
        repo = create_repository()
        if hasattr(repo, "_ensure_schema"):
            await repo._ensure_schema()
        lexicons = await repo.get_domain_lexicons()
        await repo.close()
        return True, f"Database initialized successfully with {len(lexicons)} seed lexicons."
    except Exception as e:
        return False, f"Database initialization warning: {e}"


def get_claude_desktop_config_path() -> Path:
    """Resolve OS-specific path to Claude Desktop configuration file."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "win32":
        return Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
    else:
        return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def get_cline_config_path() -> Path:
    """Resolve OS-specific path to Cline MCP configuration file."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"
    elif sys.platform == "win32":
        return Path(os.environ.get("APPDATA", "")) / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"
    else:
        return Path.home() / ".config" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"


def get_roo_code_config_path() -> Path:
    """Resolve OS-specific path to Roo Code MCP configuration file."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json"
    elif sys.platform == "win32":
        return Path(os.environ.get("APPDATA", "")) / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json"
    else:
        return Path.home() / ".config" / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json"


def build_mcp_entry(python_bin: str, project_root: Path) -> Dict[str, Any]:
    """Generate standardized MCP server entry dictionary."""
    from ignis.config import settings
    entry: Dict[str, Any] = {
        "command": python_bin,
        "args": ["-m", "ignis.interfaces.mcp.server"],
        "env": {
            "DATABASE_URL": settings.DATABASE_URL,
            "DEFAULT_GEO": getattr(settings, "DEFAULT_GEO", "VN"),
        }
    }
    return entry


def register_mcp_to_json_file(config_path: Path, entry: Dict[str, Any], key_name: str = "mcpServers") -> bool:
    """Safely register or update fn-ignis entry in an MCP JSON configuration file."""
    try:
        config_data: Dict[str, Any] = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
                backup_path = config_path.with_suffix(f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
                shutil.copy2(config_path, backup_path)
            except Exception:
                config_data = {}

        if key_name not in config_data:
            config_data[key_name] = {}

        config_data[key_name]["fn-ignis"] = entry
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"  ⚠️ Failed to write to {config_path}: {e}")
        return False


def setup_all_mcp_clients(project_root: Path, python_bin: str) -> List[Dict[str, Any]]:
    """Register fn-ignis across all supported and detected agent environments."""
    mcp_entry = build_mcp_entry(python_bin, project_root)
    results = []

    # 1. Project Root .mcp.json (Standard MCP Project Config)
    root_mcp = project_root / ".mcp.json"
    ok = register_mcp_to_json_file(root_mcp, mcp_entry, "mcpServers")
    results.append({"client": "Workspace (.mcp.json)", "path": str(root_mcp), "status": "configured" if ok else "failed"})

    # 2. Cursor IDE (.cursor/mcp.json)
    cursor_mcp = project_root / ".cursor" / "mcp.json"
    ok = register_mcp_to_json_file(cursor_mcp, mcp_entry, "mcpServers")
    results.append({"client": "Cursor IDE (.cursor/mcp.json)", "path": str(cursor_mcp), "status": "configured" if ok else "failed"})

    # 3. VS Code Workspace (.vscode/mcp.json)
    vscode_mcp = project_root / ".vscode" / "mcp.json"
    ok = register_mcp_to_json_file(vscode_mcp, mcp_entry, "mcpServers")
    results.append({"client": "VS Code Workspace (.vscode/mcp.json)", "path": str(vscode_mcp), "status": "configured" if ok else "failed"})

    # 4. Claude Desktop
    claude_path = get_claude_desktop_config_path()
    claude_parent = claude_path.parent
    if claude_parent.exists() or sys.platform in ("darwin", "win32"):
        ok = register_mcp_to_json_file(claude_path, mcp_entry, "mcpServers")
        results.append({"client": "Claude Desktop", "path": str(claude_path), "status": "configured" if ok else "failed"})

    # 5. Cline (Claude Dev)
    cline_path = get_cline_config_path()
    if cline_path.parent.exists():
        ok = register_mcp_to_json_file(cline_path, mcp_entry, "mcpServers")
        results.append({"client": "Cline Extension", "path": str(cline_path), "status": "configured" if ok else "failed"})

    # 6. Roo Code
    roo_path = get_roo_code_config_path()
    if roo_path.parent.exists():
        ok = register_mcp_to_json_file(roo_path, mcp_entry, "mcpServers")
        results.append({"client": "Roo Code Extension", "path": str(roo_path), "status": "configured" if ok else "failed"})

    return results


async def run_synthetic_diagnostics() -> Dict[str, Any]:
    """Run real-time diagnostics to ensure server readiness."""
    from ignis.infrastructure.persistence import create_repository
    from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin
    
    diag: Dict[str, Any] = {"database": "unknown", "google_rss": "unknown", "lexicon_count": 0}
    try:
        repo = create_repository()
        lexicons = await repo.get_domain_lexicons()
        diag["database"] = "ready"
        diag["lexicon_count"] = len(lexicons)
        await repo.close()
    except Exception as e:
        diag["database"] = f"error: {e}"

    try:
        rss = GoogleTrendsRssPlugin()
        rss_healthy = await rss.is_healthy()
        diag["google_rss"] = "healthy" if rss_healthy else "degraded"
    except Exception as e:
        diag["google_rss"] = f"error: {e}"

    return diag


def auto_provision(json_output: bool = False) -> Dict[str, Any]:
    """Execute complete end-to-end zero-touch auto-provisioning."""
    project_root = get_project_root()
    python_bin = sys.executable

    # 1. Environment & Fernet Key
    env_created, env_msg = ensure_environment_file(project_root)

    # 2. Database Schema Bootstrap
    db_ok, db_msg = asyncio.run(bootstrap_database())

    # 3. Multi-client MCP Registration
    client_results = setup_all_mcp_clients(project_root, python_bin)

    # 4. Run Diagnostics
    diag = asyncio.run(run_synthetic_diagnostics())

    report = {
        "status": "success" if db_ok else "warning",
        "project_root": str(project_root),
        "python_executable": python_bin,
        "environment": env_msg,
        "database": db_msg,
        "clients_configured": client_results,
        "diagnostics": diag,
        "capabilities": {
            "tools_count": 28,
            "prompts_count": 2,
            "resources_count": 2,
            "sop": "6-Step Market Opportunity & White Space Standard Operating Procedure"
        }
    }

    if json_output:
        print(json.dumps(report, indent=2))
        return report

    print("\n" + "=" * 64)
    print("🔥 fn-ignis Zero-Touch Agent Auto-Provisioning Complete")
    print("=" * 64)
    print(f"📁 Project Root: {project_root}")
    print(f"🐍 Python Executable: {python_bin}")
    print(f"⚙️  Environment: {env_msg}")
    print(f"🗄️  Database: {db_msg}")
    print("\n📦 Configured MCP Clients:")
    for c in client_results:
        print(f"  • {c['client']}: {c['status']} ({c['path']})")
    
    print("\n🩺 Diagnostics:")
    print(f"  • DB Pool / SQLite: {diag.get('database')}")
    print(f"  • Google Trends RSS: {diag.get('google_rss')}")
    print(f"  • Seed Lexicons: {diag.get('lexicon_count')} terms loaded")

    print("\n🚀 Ready for AI Agents (Claude, Cursor, Windsurf, Codex, Antigravity, OpenClaw, Hermes)")
    print("Quickstart prompt for agent:")
    print('  "Run a research mission on AI customer service agents in VN for the last 30 days"')
    print("=" * 64 + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description="fn-ignis Zero-Touch Agent Auto-Provisioner")
    parser.add_argument("--json", action="store_true", help="Output report in JSON format for automated agents")
    parser.add_argument("--all", action="store_true", default=True, help="Configure all supported clients and databases")
    args = parser.parse_args()

    auto_provision(json_output=args.json)


if __name__ == "__main__":
    main()
