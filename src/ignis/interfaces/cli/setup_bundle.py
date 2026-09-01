import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from ignis.config import settings


def get_claude_desktop_config_path() -> Path:
    """Resolve the OS-specific path to Claude Desktop configuration file."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "win32":
        return Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
    else:
        return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def setup_claude_desktop_bundle(force: bool = False) -> bool:
    """Automatically detect and register the fn-ignis MCP Server in Claude Desktop configuration."""
    config_path = get_claude_desktop_config_path()
    project_root = Path(__file__).resolve().parents[3]
    python_bin = sys.executable

    print("\n" + "=" * 60)
    print("🚀 fn-ignis Bundle Setup & Integration Installer")
    print("=" * 60)
    print(f"📁 Project Root: {project_root}")
    print(f"🐍 Python Executable: {python_bin}")
    print(f"📄 Claude Desktop Config: {config_path}")

    config_data = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
            print(f"✓ Loaded existing config ({len(config_data.get('mcpServers', {}))} MCP servers registered).")
            
            backup_path = config_path.with_suffix(f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            shutil.copy2(config_path, backup_path)
            print(f"✓ Created backup file: {backup_path.name}")
        except Exception as e:
            print(f"⚠️ Failed to parse config file: {e}. Creating new configuration.")
            config_data = {}

    if "mcpServers" not in config_data:
        config_data["mcpServers"] = {}

    fn_ignis_entry = {
        "command": python_bin,
        "args": ["-m", "ignis.interfaces.mcp.server"],
        "env": {
            "DATABASE_URL": settings.DATABASE_URL,
            "DEFAULT_GEO": getattr(settings, "DEFAULT_GEO", "VN"),
        }
    }
    if settings.YOUTUBE_API_KEY:
        fn_ignis_entry["env"]["YOUTUBE_API_KEY"] = settings.YOUTUBE_API_KEY

    config_data["mcpServers"]["fn-ignis"] = fn_ignis_entry

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)

    print(f"\n🎉 INSTALLATION SUCCESSFUL! fn-ignis is configured for Claude Desktop.")
    print("Pre-configured capabilities:")
    print("  • 15 MCP Tools (Research, Ingress, Suggestions, Creative Center, Comments, HTML Report)")
    print("  • 2 MCP Prompts (market_research_pipeline, voice_of_customer_audit)")
    print("  • 2 MCP Resources (fn-ignis://sop/market-research, fn-ignis://methodology/opportunity-index)")
    print("  • 6-Step SOP System Instructions automatically injected on session start.")
    print("\n👉 Please restart Claude Desktop to apply changes.")
    print("=" * 60 + "\n")
    return True


def main():
    setup_claude_desktop_bundle()


if __name__ == "__main__":
    main()
