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

This is the AAP Enterprise MCP Server - a Model Context Protocol server that enables AI assistants to interact with Ansible Automation Platform (AAP) and Event-Driven Ansible (EDA) infrastructure. The project consists of two main MCP servers:
- `ansible.py` - AAP integration (405 lines)
- `eda.py` - EDA integration (96 lines)

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

## Configuration Standards

### Code Style
- Black formatting with 120 character line length
- Ruff linting with comprehensive rule set (E, W, F, I, B, C4, UP)
- mypy type checking with strict configuration
- Python 3.11+ target version

### Async Patterns
All API interactions use async/await patterns with httpx client. Maintain consistency with existing async implementations when adding new functionality.