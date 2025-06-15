# AAP Enterprise MCP Server

A Model Context Protocol (MCP) server for Ansible Automation Platform (AAP) and Event-Driven Ansible (EDA), enabling AI assistants to interact with your automation infrastructure.

## Features

### Ansible Automation Platform (AAP) Integration
- **Inventory Management**: List, create, update inventories and manage hosts/groups
- **Job Management**: Run job templates, monitor job status, and retrieve logs
- **Project Management**: Create and manage SCM-based projects
- **Template Management**: Create and manage job templates
- **Host Operations**: Add/remove hosts, manage host variables and facts
- **Ad-hoc Commands**: Execute ansible commands directly on inventory hosts

### Event-Driven Ansible (EDA) Integration
- **Activation Management**: List, create, enable/disable EDA activations
- **Rulebook Management**: Manage and query rulebooks
- **Decision Environment Management**: Manage decision environments
- **Event Stream Monitoring**: Monitor event streams

## Installation

### Prerequisites
- Python 3.11 or higher
- UV package manager (recommended) or pip
- Access to an Ansible Automation Platform instance
- Valid AAP API token

### Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/sibilleb/AAP-Enterprise-MCP-Server.git
   cd AAP-Enterprise-MCP-Server
   ```

2. **Install dependencies**:
   ```bash
   # Using UV (recommended)
   uv sync
   
   # Or using pip
   pip install -e .
   ```

3. **Set up environment variables**:
   ```bash
   export AAP_TOKEN="your-aap-api-token"
   export AAP_URL="https://your-aap-server.com/api/controller/v2"
   export EDA_TOKEN="your-eda-api-token"  # Can be same as AAP_TOKEN
   export EDA_URL="https://your-aap-server.com/api/eda/v1"
   ```

## Getting Your API Token

### Method 1: AAP Web Interface
1. Log into your AAP web interface
2. Click on your username in the top right corner
3. Select "User Settings" or "My Profile"
4. Navigate to the "Tokens" section
5. Click "Add" or "Create Token"
6. Set the scope to "Write" for full functionality
7. Copy the generated token immediately (it won't be shown again)

### Method 2: Command Line
```bash
curl -k -X POST \
  "https://your-aap-server.com/api/v2/tokens/" \
  -H "Content-Type: application/json" \
  -u "username:password" \
  -d '{
    "description": "MCP Server Token",
    "application": null,
    "scope": "write"
  }'
```

## Configuration

### MCP Client Configuration

Add the following to your MCP client configuration (e.g., Claude Desktop, Cursor):

```json
{
  "mcpServers": {
    "ansible": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/AAP-Enterprise-MCP-Server",
        "run",
        "ansible.py"
      ],
      "env": {
        "AAP_TOKEN": "your-aap-api-token",
        "AAP_URL": "https://your-aap-server.com/api/controller/v2"
      }
    },
    "eda": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/AAP-Enterprise-MCP-Server",
        "run",
        "eda.py"
      ],
      "env": {
        "EDA_TOKEN": "your-eda-api-token",
        "EDA_URL": "https://your-aap-server.com/api/eda/v1"
      }
    }
  }
}
```

### SSL/TLS Configuration

For lab environments with self-signed certificates, the servers automatically:
- Disable SSL warnings
- Skip certificate verification
- Handle insecure connections gracefully

For production environments, ensure proper SSL certificates are configured on your AAP instance.

## Available Tools

### Ansible Automation Platform Tools

| Tool | Description |
|------|-------------|
| `list_inventories` | List all inventories |
| `get_inventory` | Get inventory details by ID |
| `create_inventory` | Create a new inventory |
| `list_hosts` | List hosts in an inventory |
| `add_host_to_inventory` | Add a host to inventory |
| `run_job` | Execute a job template |
| `job_status` | Check job execution status |
| `job_logs` | Retrieve job execution logs |
| `list_job_templates` | List available job templates |
| `create_job_template` | Create a new job template |
| `create_project` | Create a new project |
| `run_adhoc_command` | Execute ad-hoc ansible commands |

### Event-Driven Ansible Tools

| Tool | Description |
|------|-------------|
| `list_activations` | List EDA activations |
| `get_activation` | Get activation details |
| `create_activation` | Create new activation |
| `enable_activation` | Enable an activation |
| `disable_activation` | Disable an activation |
| `restart_activation` | Restart an activation |
| `list_rulebooks` | List available rulebooks |
| `get_rulebook` | Get rulebook details |
| `list_decision_environments` | List decision environments |

## Usage Examples

### Running a Job Template
```python
# List available job templates
templates = await list_job_templates()

# Run a specific job template with variables
result = await run_job(
    template_id=5,
    extra_vars={"target_env": "production", "app_version": "1.2.3"}
)

# Check job status
status = await job_status(result["job"])
```

### Managing Inventory
```python
# List all inventories
inventories = await list_inventories()

# Add a new host to inventory
await add_host_to_inventory(
    inventory_id=1,
    hostname="web-server-01.example.com",
    variables={"ansible_host": "192.168.1.100", "role": "webserver"}
)

# Run ad-hoc command on inventory
await run_adhoc_command(
    inventory_id=1,
    module_name="setup",
    limit="web-server-01.example.com"
)
```

### EDA Activation Management
```python
# List all activations
activations = await list_activations()

# Enable a specific activation
await enable_activation(activation_id=3)

# Check activation details
details = await get_activation(activation_id=3)
```

## Development

### Running Tests
```bash
# Install development dependencies
uv sync --group dev

# Run tests
pytest

# Run with coverage
pytest --cov=.
```

### Code Formatting
```bash
# Format code
black .

# Lint code
ruff check .

# Type checking
mypy .
```

## Troubleshooting

### Common Issues

1. **SSL Certificate Errors**: The server handles self-signed certificates automatically. If you encounter SSL issues, verify your AAP server configuration.

2. **Authentication Failures**: Ensure your API token has sufficient permissions (Write scope recommended).

3. **Connection Timeouts**: Check network connectivity to your AAP server and verify the URL format.

4. **Tool Not Found**: Restart your MCP client after configuration changes.

### Debug Mode

Set environment variable for verbose logging:
```bash
export MCP_DEBUG=1
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- GitHub Issues: [Report bugs and request features](https://github.com/sibilleb/AAP-Enterprise-MCP-Server/issues)
- Documentation: [README](README.md)
- Ansible Community: [Ansible Community Forum](https://forum.ansible.com/)

## Related Projects

- [Ansible Automation Platform](https://www.redhat.com/en/technologies/management/ansible)
- [Event-Driven Ansible](https://www.redhat.com/en/technologies/management/ansible/event-driven-ansible)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [FastMCP](https://github.com/punkpeye/fastmcp)
- [MCP](https://github.com/rlopez133/mcp)