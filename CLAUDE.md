# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Information

- **Repository**: https://github.com/sibilleb/AAP-Enterprise-MCP-Server
- **Owner**: sibilleb
- **Project**: AAP Enterprise MCP Server

## Commit Message Guidelines

- **NEVER** include "Generated with Claude Code" or similar AI generation attributions in commit messages
- Keep commit messages professional and focused on the actual changes
- Use conventional commit format when appropriate
- Do not add Co-Authored-By: Claude attributions

## Project Overview

This is the AAP Enterprise MCP Server - a Model Context Protocol server that enables AI assistants to interact with Ansible Automation Platform (AAP), Event-Driven Ansible (EDA), and ansible-lint for code quality assurance. The project consists of three main MCP servers:
- `ansible.py` - AAP integration with Galaxy search (855 lines)
- `eda.py` - EDA integration (96 lines)  
- `ansible-lint.py` - Code quality and linting tools (502 lines)

## Development Commands

### Package Management
```bash
# Install dependencies (preferred)
uv sync

# Install with pip
pip install -e .

# Install development dependencies
uv sync --group dev
```

### Code Quality
```bash
# Format code
black .

# Lint code
ruff check .

# Type checking
mypy .
```

### Testing
```bash
# Run tests
pytest

# Run tests with coverage
pytest --cov=.
```

### Running the Servers
```bash
# Run AAP MCP server
uv run ansible.py

# Run EDA MCP server
uv run eda.py

# Run ansible-lint MCP server
uv run ansible-lint.py
```

## Architecture

### Core Structure
- **Framework**: FastMCP (built on MCP protocol)
- **HTTP Client**: httpx for async API calls
- **Language**: Python 3.11+
- **Authentication**: Bearer token-based

### Key Components
- **Inventory Management**: 15+ tools for managing inventories, hosts, and groups
- **Job Management**: Run job templates, monitor status, retrieve logs
- **Project Management**: Create and manage SCM-based projects
- **Ad-hoc Commands**: Execute ansible commands directly
- **EDA Integration**: Activation, rulebook, and decision environment management
- **Galaxy Search**: Discover collections and roles with intelligent recommendations
- **Code Quality**: Ansible-lint integration for best practices and validation

### Environment Variables
Required for operation:
- `AAP_TOKEN`: API token for AAP authentication
- `AAP_URL`: AAP API endpoint (e.g., `https://server.com/api/controller/v2`)
- `EDA_TOKEN`: API token for EDA authentication  
- `EDA_URL`: EDA API endpoint (e.g., `https://server.com/api/eda/v1`)

### SSL Handling
The servers automatically handle self-signed certificates for lab environments by:
- Disabling SSL warnings via urllib3
- Skipping certificate verification
- Using httpx with SSL verification disabled

### Error Handling
- Graceful handling of authentication failures
- Proper error messages for missing environment variables
- SSL/TLS connection error handling for lab environments

### Galaxy Search Integration
The MCP server includes comprehensive Ansible Galaxy search capabilities:

#### Galaxy Tools Available
- `search_galaxy_collections(query, tags, namespace, limit)` - Search collections by various criteria
- `search_galaxy_roles(keyword, name, author, limit)` - Find roles using flexible search parameters
- `get_collection_details(namespace, name)` - Get detailed collection information including versions
- `get_role_details(role_id)` - Get comprehensive role details and metadata
- `suggest_ansible_content(use_case, check_aap_inventory)` - AI-powered content suggestions

#### Smart Content Discovery
The `suggest_ansible_content` tool provides intelligent recommendations by:
- Analyzing use case descriptions for keywords and technology patterns
- Checking existing AAP inventories and infrastructure (when enabled)
- Searching Galaxy for relevant collections and roles
- Ranking results by relevance, popularity, and compatibility
- Generating specific playbook suggestions with example tasks

#### Galaxy Search Implementation Notes
**Collections Search**: Uses Galaxy v3 API `/api/v3/plugin/ansible/content/published/collections/index/` with local filtering since direct keyword search is not supported. This approach:
- Fetches collection data from the stable endpoint
- Performs client-side filtering by namespace and name
- Returns consistent results with proper error handling
- Avoids dependency on potentially unstable search APIs

**Roles Search**: Uses Galaxy v1 API `/api/v1/roles/` which has native keyword search support.

**Error Handling**: All Galaxy tools return string error messages when API calls fail, ensuring graceful degradation.

#### Usage Patterns
When users describe automation needs (e.g., "deploy EC2 servers on AWS"), use:
1. `suggest_ansible_content()` first for comprehensive recommendations
2. `search_galaxy_collections()` for specific collection searches
3. `search_galaxy_roles()` for finding community roles
4. Detail tools for specific collection/role information

#### Content Analysis
The Galaxy tools extract and analyze:
- Cloud providers (AWS, Azure, GCP, OpenStack)
- Infrastructure components (web, database, containers, networking)
- Action keywords (deploy, configure, manage, scale)
- Technology stack indicators

### Ansible Lint Integration
The project includes a dedicated ansible-lint MCP server for code quality assurance:

#### Lint Tools Available
- `lint_playbook(content, profile, format_type, rules)` - Lint playbook content with configurable profiles
- `lint_file(file_path, profile, format_type)` - Lint specific Ansible files on disk
- `lint_role(role_path, profile)` - Comprehensive role validation with structure analysis
- `validate_syntax(content)` - Quick syntax-only validation for immediate feedback
- `check_best_practices(content, context, exclude_rules)` - Context-aware best practice checking
- `analyze_project(project_path, profile)` - Full project structure analysis and reporting
- `list_rules(tags)` - List available rules, filterable by tags
- `list_tags()` - List all available rule tags
- `get_ansible_lint_version()` - Get version information

#### Quality Profiles
Use progressive profiles for quality improvement:
- **min**: Basic validation, ensures Ansible can load content
- **basic**: Standard checks for development (default for most use cases)
- **moderate**: More comprehensive validation for staging environments
- **safety**: Focus on security and reliability concerns
- **shared**: Standards for shared/published content
- **production**: Strictest rules for production-ready code

#### Context-Aware Usage
- **Development**: Use `basic` profile for rapid iteration
- **Code Review**: Use `moderate` profile for comprehensive checking
- **Pre-Production**: Use `safety` profile to catch security issues
- **Production Deployment**: Use `production` profile for final validation

#### Integration Patterns
- **Real-time Validation**: Use `validate_syntax()` for immediate feedback during editing
- **Progressive Quality**: Start with `basic` profile and progress to `production`
- **Project Analysis**: Use `analyze_project()` for comprehensive project health checks
- **Learning Tool**: Use `list_rules()` and rule explanations to understand best practices

#### Error Handling
The ansible-lint server gracefully handles:
- Missing ansible-lint installation (returns helpful error messages)
- Invalid YAML syntax (provides structured error information)
- File system access issues (clear error reporting)
- Command timeouts (60-second limit with timeout handling)

## Configuration Standards

### Code Style
- Black formatting with 120 character line length
- Ruff linting with comprehensive rule set (E, W, F, I, B, C4, UP)
- mypy type checking with strict configuration
- Python 3.11+ target version

### Async Patterns
All API interactions use async/await patterns with httpx client. Maintain consistency with existing async implementations when adding new functionality.

### Three-Server Architecture
The project follows a modular architecture with three specialized MCP servers:

1. **ansible.py** - Core AAP integration and Galaxy search
   - Handles all AAP API interactions
   - Provides Galaxy collection and role discovery
   - Includes intelligent content recommendations
   - Manages inventory, jobs, projects, and ad-hoc commands

2. **eda.py** - Event-Driven Ansible integration
   - Manages EDA activations and rulebooks
   - Handles decision environments
   - Monitors event streams

3. **ansible-lint.py** - Code quality assurance
   - Provides ansible-lint integration
   - Offers progressive quality profiles
   - Includes project-wide analysis tools
   - Supports real-time syntax validation

This separation allows for:
- Focused functionality per server
- Independent scaling and deployment
- Specialized error handling per domain
- Cleaner MCP client configuration