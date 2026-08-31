import mcp.shared.exceptions

# Compatibility bridge between mcp >= 2.0 (MCPError) and fastmcp (McpError)
if not hasattr(mcp.shared.exceptions, "McpError") and hasattr(mcp.shared.exceptions, "MCPError"):
    mcp.shared.exceptions.McpError = mcp.shared.exceptions.MCPError
