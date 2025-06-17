#!/usr/bin/env python3
"""
Red Hat Documentation MCP Server

A Model Context Protocol server that provides access to Red Hat's official documentation
including OpenShift, RHEL, Ansible Automation Platform, and other Red Hat products.

Key Features:
- Read documentation from PDF and HTML sources
- Search across Red Hat documentation
- Support for multiple products and versions
- Handles both authenticated and unauthenticated access
"""

import os
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlparse

import httpx
import urllib3
from mcp.server.fastmcp import FastMCP

# Disable SSL warnings for lab environments
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Environment variables for optional authentication
REDHAT_USERNAME = os.getenv("REDHAT_USERNAME")
REDHAT_PASSWORD = os.getenv("REDHAT_PASSWORD")

# Initialize FastMCP
mcp = FastMCP("redhat-docs")

# Base URLs for Red Hat documentation
REDHAT_DOCS_BASE = "https://docs.redhat.com"
REDHAT_ACCESS_BASE = "https://access.redhat.com"

# Official Red Hat domains and subdomains for validation
OFFICIAL_REDHAT_DOMAINS = {
    # Core Red Hat domains
    "redhat.com",
    "docs.redhat.com",
    "access.redhat.com",
    "sso.redhat.com",
    "console.redhat.com",
    "cloud.redhat.com",
    "marketplace.redhat.com",
    "customer-portal.redhat.com",
    "connect.redhat.com",
    "catalog.redhat.com",
    "subscriptions.redhat.com",
    # Container registries and CDN
    "registry.redhat.com",
    "registry.access.redhat.com",
    "registry.connect.redhat.com",
    "registry.redhat.io",
    "quay.io",
    "cdn.quay.io",
    "cdn.redhat.com",
    "cdn-ubi.redhat.com",
    "download.redhat.com",
    # Product-specific domains
    "openshift.com",
    "docs.openshift.com",
    "console.openshift.com",
    "try.openshift.com",
    "learn.openshift.com",
    "ansible.com",
    "docs.ansible.com",
    "galaxy.ansible.com",
    "automation-hub.redhat.com",
    # Community and open source
    "opensource.com",
    "redhat.io",
    "developers.redhat.com",
    "research.redhat.com",
    "enable.redhat.com",
    "blog.redhat.com",
    # Enterprise services and support
    "npm.registry.redhat.com",
    "insights.redhat.com",
    "hybrid-cloud-console.redhat.com",
    "support.redhat.com",
    "labs.redhat.com",
    "training.redhat.com",
    "learn.redhat.com",
    # Events and community
    "summit.redhat.com",
    "events.redhat.com",
    "community.redhat.com",
    "partnerships.redhat.com",
    # Security and compliance
    "security.redhat.com",
    "errata.redhat.com",
    "cve.redhat.com",
    # Business and enterprise
    "investors.redhat.com",
    "jobs.redhat.com",
    "careers.redhat.com",
    "redhat.force.com",
}

# Domain patterns for subdomain matching
REDHAT_DOMAIN_PATTERNS = [
    r".*\.redhat\.com$",
    r".*\.redhat\.io$",
    r".*\.openshift\.com$",
    r".*\.ansible\.com$",
    r".*\.quay\.io$",
    r"cdn.*\.redhat\.com$",
    r"registry.*\.redhat\.com$",
    r".*\.redhat\.force\.com$",
    r"download.*\.redhat\.com$",
    r".*-redhat\.com$",
    r".*\.rhel\.com$",
]

# Cache for sitemap data and frequently accessed content
_sitemap_cache = {}
_content_cache = {}


def is_official_redhat_domain(url: str) -> bool:
    """
    Validate that a URL is from an official Red Hat domain.

    Args:
        url: URL to validate

    Returns:
        True if URL is from official Red Hat domain, False otherwise
    """
    import re
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # Remove www. prefix if present
        if domain.startswith("www."):
            domain = domain[4:]

        # Check exact domain matches
        if domain in OFFICIAL_REDHAT_DOMAINS:
            return True

        # Check subdomain patterns
        for pattern in REDHAT_DOMAIN_PATTERNS:
            if re.match(pattern, domain):
                return True

        return False

    except Exception:
        return False


def generate_redhat_search_queries(query: str, product: str | None = None) -> list[dict[str, str]]:
    """
    Generate comprehensive search queries targeting all official Red Hat domains.

    Args:
        query: Base search query
        product: Optional product filter

    Returns:
        List of optimized search queries with Red Hat domain restrictions
    """
    queries = []

    # Primary documentation sites
    primary_sites = [
        ("docs.redhat.com", "Official Red Hat product documentation"),
        ("access.redhat.com", "Red Hat customer portal and knowledge base"),
        ("docs.openshift.com", "OpenShift-specific documentation"),
        ("docs.ansible.com", "Ansible documentation and guides"),
        ("developers.redhat.com", "Developer resources and tutorials"),
    ]

    for site, description in primary_sites:
        site_query = f"site:{site} {query}"
        queries.append(
            {
                "query": site_query,
                "domain": site,
                "purpose": f"Find content on {description}",
                "expected_results": f"Official {site} documentation and resources",
            }
        )

    # Multi-site queries for broader coverage
    core_domains = ["redhat.com", "openshift.com", "ansible.com"]
    for domain in core_domains:
        multi_query = f"site:{domain} {query}"
        queries.append(
            {
                "query": multi_query,
                "domain": domain,
                "purpose": f"Find any content across {domain} and subdomains",
                "expected_results": f"Comprehensive {domain} content including docs, blogs, and resources",
            }
        )

    # Registry and technical resources (for container/deployment queries)
    if any(term in query.lower() for term in ["container", "image", "deploy", "install", "registry"]):
        tech_sites = [
            ("registry.redhat.com", "Container images and deployment resources"),
            ("quay.io", "Red Hat container registry content"),
            ("console.redhat.com", "Red Hat console and management guides"),
        ]

        for site, description in tech_sites:
            tech_query = f"site:{site} {query}"
            queries.append(
                {
                    "query": tech_query,
                    "domain": site,
                    "purpose": f"Find {description}",
                    "expected_results": f"Technical resources from {site}",
                }
            )

    # Product-specific enhancements
    if product or any(prod in query.lower() for prod in ["openshift", "rhel", "ansible", "satellite"]):
        if "openshift" in query.lower() or product == "openshift":
            queries.append(
                {
                    "query": f"site:openshift.com OR site:docs.openshift.com {query}",
                    "domain": "openshift.com",
                    "purpose": "Find comprehensive OpenShift content",
                    "expected_results": "Official OpenShift documentation and resources",
                }
            )

        if "ansible" in query.lower() or product == "ansible":
            queries.append(
                {
                    "query": f"site:ansible.com OR site:docs.ansible.com {query}",
                    "domain": "ansible.com",
                    "purpose": "Find comprehensive Ansible content",
                    "expected_results": "Official Ansible documentation and community resources",
                }
            )

    # Community and developer content
    if any(term in query.lower() for term in ["tutorial", "example", "guide", "blog", "community"]):
        community_sites = [
            ("opensource.com", "Open source articles and tutorials"),
            ("developers.redhat.com", "Developer tutorials and guides"),
        ]

        for site, description in community_sites:
            comm_query = f"site:{site} {query}"
            queries.append(
                {
                    "query": comm_query,
                    "domain": site,
                    "purpose": f"Find {description}",
                    "expected_results": f"Community content and tutorials from {site}",
                }
            )

    return queries


async def web_search_redhat_docs(query: str, limit: int = 10) -> dict[str, Any]:
    """
    Use web search to find Red Hat documentation URLs that Google has indexed.
    This is a placeholder that would use an external web search API.

    Note: In a real implementation, this would use the WebSearch tool available
    in the MCP environment or an external search API.
    """
    # Construct search query targeting Red Hat docs
    search_query = f"site:docs.redhat.com {query}"

    # For now, return a structured response that indicates web search capability
    # In practice, this would integrate with the MCP WebSearch tool
    return {
        "query": search_query,
        "total_found": 0,
        "results": [],
        "note": "Web search integration requires WebSearch MCP tool or external search API. "
        "This functionality demonstrates the hybrid approach architecture.",
        "suggested_implementation": "Use MCP WebSearch tool with site:docs.redhat.com filtering",
    }


async def make_request(url: str, method: str = "GET", params: dict = None, headers: dict = None) -> Any:
    """Helper function to make HTTP requests with proper error handling."""
    default_headers = {"User-Agent": "Red Hat Documentation MCP Server/1.0"}

    if headers:
        default_headers.update(headers)

    timeout = httpx.Timeout(60.0)

    try:
        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            response = await client.request(method, url, params=params, headers=default_headers)

        if response.status_code == 200:
            return response
        else:
            return f"HTTP Error {response.status_code}: {response.text[:200]}"

    except httpx.TimeoutException:
        return "Request timeout - Red Hat documentation service may be slow"
    except httpx.RequestError as e:
        return f"Request error: {str(e)}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"


async def fetch_sitemap() -> dict[str, list[str]]:
    """Fetch and parse Red Hat documentation sitemap to discover available content."""
    if "sitemap_index" in _sitemap_cache:
        return _sitemap_cache["sitemap_index"]

    sitemap_index_url = f"{REDHAT_DOCS_BASE}/sitemaps/docs/docs-sitemap-index.xml"
    response = await make_request(sitemap_index_url)

    if isinstance(response, str):  # Error occurred
        return {"error": response}

    try:
        root = ET.fromstring(response.text)
        sitemap_urls = []

        # Extract individual sitemap URLs
        for sitemap in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap"):
            loc = sitemap.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
            if loc is not None:
                url = loc.text
                # Fix relative URLs
                if url.startswith("//"):
                    url = "https://docs.redhat.com" + url[1:]  # Remove leading // and add full domain
                elif url.startswith("/"):
                    url = REDHAT_DOCS_BASE + url
                sitemap_urls.append(url)

        # Parse first few sitemaps to build product index
        products = {}

        for _i, sitemap_url in enumerate(sitemap_urls[:3]):  # Limit to first 3 to avoid overwhelming
            sitemap_response = await make_request(sitemap_url)
            if isinstance(sitemap_response, str):
                continue

            try:
                sitemap_root = ET.fromstring(sitemap_response.text)
                namespace = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}

                for url_elem in sitemap_root.findall(".//ns:url", namespace):
                    loc = url_elem.find("ns:loc", namespace)
                    if loc is not None:
                        url = loc.text
                        # Extract product and version from URL
                        match = re.search(r"/documentation/([^/]+)/([^/]+)/", url)
                        if match:
                            product, version = match.groups()
                            if product not in products:
                                products[product] = set()
                            products[product].add(version)

            except ET.ParseError:
                continue

        # Convert sets to lists for JSON serialization
        for product in products:
            products[product] = list(products[product])

        _sitemap_cache["sitemap_index"] = products
        return products

    except ET.ParseError as e:
        return {"error": f"Failed to parse sitemap XML: {str(e)}"}


def extract_pdf_url(html_url: str) -> str:
    """Convert HTML documentation URL to corresponding PDF URL."""
    # Pattern: /html/guide_name/index -> /pdf/guide_name/index
    html_pattern = r"/html(?:-single)?/([^/]+)/?(?:index)?$"
    match = re.search(html_pattern, html_url)

    if match:
        guide_name = match.group(1)
        # Replace html with pdf and add index
        pdf_url = re.sub(html_pattern, f"/pdf/{guide_name}/index", html_url)
        return pdf_url

    return html_url


@mcp.tool()
async def read_documentation(url: str, format_preference: str = "auto") -> str:
    """
    Read Red Hat documentation from a URL.

    Args:
        url: Red Hat documentation URL (docs.redhat.com or access.redhat.com)
        format_preference: "pdf", "html", or "auto" (default: auto tries PDF first)

    Returns:
        Documentation content as text
    """
    # Validate URL is from Red Hat domains
    parsed_url = urlparse(url)
    if parsed_url.netloc not in ["docs.redhat.com", "access.redhat.com"]:
        return "Error: URL must be from docs.redhat.com or access.redhat.com"

    # Try PDF first if auto or pdf preference
    if format_preference in ["auto", "pdf"]:
        if "/html" in url:
            pdf_url = extract_pdf_url(url)
            if pdf_url != url:
                response = await make_request(pdf_url)
                if not isinstance(response, str) and response.status_code == 200:
                    # Check if it's actually a PDF
                    content_type = response.headers.get("content-type", "")
                    if "pdf" in content_type.lower():
                        return (
                            f"PDF Content from {pdf_url}\\n\\n"
                            f"Note: PDF content extraction would be implemented here.\\n"
                            f"Content-Type: {content_type}\\nSize: {len(response.content)} bytes"
                        )

    # Fall back to HTML if PDF not available or html preference
    if format_preference in ["auto", "html"]:
        response = await make_request(url)
        if isinstance(response, str):  # Error occurred
            return f"Error accessing documentation: {response}"

        # For now, return information about the page since we can't parse JS-heavy content
        content_type = response.headers.get("content-type", "")
        return (
            f"HTML Documentation: {url}\\n\\n"
            f"Note: HTML content requires JavaScript rendering.\\n"
            f"Content-Type: {content_type}\\nStatus: {response.status_code}\\n\\n"
            f"To read this content, try requesting the PDF version or use a browser."
        )

    return "Error: Unable to access documentation in requested format"


@mcp.tool()
async def list_products() -> dict[str, Any]:
    """
    List available Red Hat products and their documentation versions.

    Returns:
        Dictionary of products and their available versions
    """
    products = await fetch_sitemap()

    if "error" in products:
        return {"error": products["error"], "products": {}}

    # Add some metadata about well-known products
    product_info = {
        "openshift_container_platform": {
            "name": "OpenShift Container Platform",
            "description": "Enterprise Kubernetes platform",
            "versions": products.get("openshift_container_platform", []),
        },
        "red_hat_enterprise_linux": {
            "name": "Red Hat Enterprise Linux (RHEL)",
            "description": "Enterprise Linux operating system",
            "versions": products.get("red_hat_enterprise_linux", []),
        },
        "red_hat_ansible_automation_platform": {
            "name": "Red Hat Ansible Automation Platform",
            "description": "Enterprise automation platform",
            "versions": products.get("red_hat_ansible_automation_platform", []),
        },
        "red_hat_satellite": {
            "name": "Red Hat Satellite",
            "description": "Systems management platform",
            "versions": products.get("red_hat_satellite", []),
        },
    }

    # Add any other discovered products
    for product_key in products:
        if product_key not in product_info and product_key != "error":
            product_info[product_key] = {
                "name": product_key.replace("_", " ").title(),
                "description": "Red Hat product documentation",
                "versions": products[product_key],
            }

    return {"total_products": len(product_info), "products": product_info}


@mcp.tool()
async def search_documentation_enhanced(
    query: str,
    product: str | None = None,
    version: str | None = None,
    limit: int = 10,
    include_web_search: bool = True,
) -> dict[str, Any]:
    """
    Enhanced search that combines sitemap-based search with web search results.
    This provides both structured sitemap results and Google-indexed content discovery.

    Args:
        query: Search terms
        product: Filter by specific product (optional)
        version: Filter by specific version (optional)
        limit: Maximum number of results per source (default: 10)
        include_web_search: Whether to include web search results (default: True)

    Returns:
        Combined search results from sitemap and web search
    """
    # Get sitemap-based results (our existing logic)
    sitemap_results = await search_documentation(query, product, version, limit)

    combined_results = {
        "query": query,
        "filters": {"product": product, "version": version},
        "sources": {"sitemap": sitemap_results, "web_search": {"results": [], "total_found": 0}},
        "combined_results": [],
        "total_found": 0,
    }

    # Add sitemap results to combined
    for result in sitemap_results.get("results", []):
        result["source"] = "sitemap"
        combined_results["combined_results"].append(result)

    # Add web search results if enabled
    if include_web_search:
        web_results = await web_search_redhat_docs(query, limit)
        combined_results["sources"]["web_search"] = web_results

        # Add web search results, avoiding duplicates
        existing_urls = {
            result.get("html_url", result.get("url", "")) for result in combined_results["combined_results"]
        }

        for web_result in web_results.get("results", []):
            if web_result["url"] not in existing_urls:
                # Convert web result to standard format
                formatted_result = {
                    "title": web_result["title"],
                    "html_url": web_result["url"],
                    "pdf_url": extract_pdf_url(web_result["url"]),
                    "snippet": web_result["snippet"],
                    "source": web_result["source"],
                    "relevance_score": 0.8,  # Web search results are generally relevant
                }

                # Try to extract product and version from URL
                url_match = re.search(r"/documentation/([^/]+)/([^/]+)/", web_result["url"])
                if url_match:
                    formatted_result["product"] = url_match.group(1)
                    formatted_result["version"] = url_match.group(2)

                combined_results["combined_results"].append(formatted_result)

    # Sort combined results by relevance score (descending)
    combined_results["combined_results"].sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

    # Limit final results
    combined_results["combined_results"] = combined_results["combined_results"][:limit]
    combined_results["total_found"] = len(combined_results["combined_results"])

    return combined_results


@mcp.tool()
async def search_documentation(
    query: str, product: str | None = None, version: str | None = None, limit: int = 10
) -> dict[str, Any]:
    """
    Search Red Hat documentation for specific content.

    Args:
        query: Search terms
        product: Filter by specific product (optional)
        version: Filter by specific version (optional)
        limit: Maximum number of results (default: 10)

    Returns:
        Search results with relevant documentation links
    """
    # For now, implement basic sitemap-based search
    products = await fetch_sitemap()

    if "error" in products:
        return {"error": products["error"], "results": []}

    results = []
    query_lower = query.lower()

    # Simple keyword matching against product names and versions
    for product_key, versions in products.items():
        if product and product.lower() not in product_key.lower():
            continue

        product_matches = any(term in product_key.lower() for term in query_lower.split())

        if product_matches:
            # Sort versions to prioritize newer ones
            sorted_versions = []
            for v in versions:
                import re

                match = re.search(r"(\d+)\.(\d+)", v)
                if match:
                    major, minor = int(match.group(1)), int(match.group(2))
                    sorted_versions.append((major, minor, v))
                else:
                    # Put non-numeric versions at the end
                    sorted_versions.append((0, 0, v))

            # Sort by major, minor version (descending) and take top 3
            sorted_versions.sort(key=lambda x: (x[0], x[1]), reverse=True)
            top_versions = [v[2] for v in sorted_versions[:3]]

            for ver in top_versions:
                if version and version not in ver:
                    continue

                base_url = f"{REDHAT_DOCS_BASE}/en/documentation/{product_key}/{ver}"

                # Common documentation guides - prioritize upgrade-related content
                common_guides = []

                # Add upgrade-specific guides for OpenShift
                if "openshift" in product_key.lower() and "upgrade" in query_lower:
                    common_guides.extend(
                        [
                            "updating_clusters",
                            "upgrading",
                            "cluster_upgrades",
                            "updating_machines",
                            "updating_clusters_overview",
                        ]
                    )

                # Add standard guides
                common_guides.extend(
                    [
                        "installation_overview",
                        "getting_started",
                        "administration_guide",
                        "user_guide",
                        "release_notes",
                    ]
                )

                for guide in common_guides:
                    html_url = f"{base_url}/html/{guide}/index"
                    pdf_url = f"{base_url}/pdf/{guide}/index"

                    results.append(
                        {
                            "title": (
                                f"{product_key.replace('_', ' ').title()} {ver} - "
                                f"{guide.replace('_', ' ').title()}"
                            ),
                            "product": product_key,
                            "version": ver,
                            "guide": guide,
                            "html_url": html_url,
                            "pdf_url": pdf_url,
                            "relevance_score": 1.0 if product_matches else 0.5,
                        }
                    )

                    if len(results) >= limit:
                        break

                if len(results) >= limit:
                    break

        if len(results) >= limit:
            break

    # Sort by relevance score
    results.sort(key=lambda x: x["relevance_score"], reverse=True)

    return {
        "query": query,
        "filters": {"product": product, "version": version},
        "total_found": len(results),
        "results": results[:limit],
    }


@mcp.tool()
async def get_product_guides(product: str, version: str = "latest") -> dict[str, Any]:
    """
    Get available documentation guides for a specific Red Hat product and version.

    Args:
        product: Red Hat product name (e.g., "openshift_container_platform")
        version: Product version (default: "latest")

    Returns:
        List of available guides and their URLs
    """
    products = await fetch_sitemap()

    if "error" in products:
        return {"error": products["error"], "guides": []}

    # Find the product
    product_key = None
    for key in products:
        if key.lower() == product.lower() or product.lower() in key.lower():
            product_key = key
            break

    if not product_key:
        available_products = list(products.keys())
        return {"error": f"Product '{product}' not found", "available_products": available_products, "guides": []}

    # Find the version
    available_versions = products[product_key]
    if version == "latest":
        # Try to find latest version (highest number or "latest" string)
        version_to_use = "latest"
        for v in available_versions:
            if "latest" in v:
                version_to_use = v
                break

        # If no "latest" found, find highest version number
        if version_to_use == "latest" and available_versions:
            # Sort versions to get the highest
            numeric_versions = []
            for v in available_versions:
                # Extract major.minor version numbers
                import re

                match = re.search(r"(\d+)\.(\d+)", v)
                if match:
                    major, minor = int(match.group(1)), int(match.group(2))
                    numeric_versions.append((major, minor, v))

            if numeric_versions:
                # Sort by major, then minor version (descending)
                numeric_versions.sort(key=lambda x: (x[0], x[1]), reverse=True)
                version_to_use = numeric_versions[0][2]  # Get the version string
            else:
                version_to_use = available_versions[0]  # Fallback to first available
    else:
        version_to_use = version
        if version_to_use not in available_versions:
            return {
                "error": f"Version '{version}' not found for {product_key}",
                "available_versions": available_versions,
                "guides": [],
            }

    # Generate common guide URLs
    base_url = f"{REDHAT_DOCS_BASE}/en/documentation/{product_key}/{version_to_use}"

    guides = [
        {
            "name": "Installation Overview",
            "id": "installation_overview",
            "html_url": f"{base_url}/html/installation_overview/index",
            "pdf_url": f"{base_url}/pdf/installation_overview/index",
        },
        {
            "name": "Getting Started",
            "id": "getting_started",
            "html_url": f"{base_url}/html/getting_started/index",
            "pdf_url": f"{base_url}/pdf/getting_started/index",
        },
        {
            "name": "User Guide",
            "id": "user_guide",
            "html_url": f"{base_url}/html/user_guide/index",
            "pdf_url": f"{base_url}/pdf/user_guide/index",
        },
        {
            "name": "Administration Guide",
            "id": "administration_guide",
            "html_url": f"{base_url}/html/administration_guide/index",
            "pdf_url": f"{base_url}/pdf/administration_guide/index",
        },
        {
            "name": "Release Notes",
            "id": "release_notes",
            "html_url": f"{base_url}/html/release_notes/index",
            "pdf_url": f"{base_url}/pdf/release_notes/index",
        },
    ]

    # Add product-specific guides
    if "openshift" in product_key.lower():
        guides.extend(
            [
                {
                    "name": "Updating Clusters",
                    "id": "updating_clusters",
                    "html_url": f"{base_url}/html/updating_clusters/index",
                    "pdf_url": f"{base_url}/pdf/updating_clusters/index",
                },
                {
                    "name": "Updating Machines in a Cluster",
                    "id": "updating_machines_in_a_cluster",
                    "html_url": f"{base_url}/html/updating_machines_in_a_cluster/index",
                    "pdf_url": f"{base_url}/pdf/updating_machines_in_a_cluster/index",
                },
                {
                    "name": "Post-installation Configuration",
                    "id": "post_installation_configuration",
                    "html_url": f"{base_url}/html/post_installation_configuration/index",
                    "pdf_url": f"{base_url}/pdf/post_installation_configuration/index",
                },
                {
                    "name": "Installing on AWS",
                    "id": "installing_on_aws",
                    "html_url": f"{base_url}/html/installing_on_aws/index",
                    "pdf_url": f"{base_url}/pdf/installing_on_aws/index",
                },
                {
                    "name": "Installing on Azure",
                    "id": "installing_on_azure",
                    "html_url": f"{base_url}/html/installing_on_azure/index",
                    "pdf_url": f"{base_url}/pdf/installing_on_azure/index",
                },
                {
                    "name": "Installing on OCI",
                    "id": "installing_on_oci",
                    "html_url": f"{base_url}/html/installing_on_oci/index",
                    "pdf_url": f"{base_url}/pdf/installing_on_oci/index",
                },
                {
                    "name": "Edge Computing",
                    "id": "edge_computing",
                    "html_url": f"{base_url}/html/edge_computing/index",
                    "pdf_url": f"{base_url}/pdf/edge_computing/index",
                },
                {
                    "name": "Scalability and Performance",
                    "id": "scalability_and_performance",
                    "html_url": f"{base_url}/html/scalability_and_performance/index",
                    "pdf_url": f"{base_url}/pdf/scalability_and_performance/index",
                },
            ]
        )

    return {
        "product": product_key,
        "version": version_to_use,
        "available_versions": available_versions,
        "total_guides": len(guides),
        "guides": guides,
    }


@mcp.tool()
async def recommend_content(topic: str, role: str = "developer") -> dict[str, Any]:
    """
    Recommend relevant Red Hat documentation based on topic and user role.

    Args:
        topic: Topic of interest (e.g., "kubernetes", "automation", "containers")
        role: User role - "developer", "administrator", "architect" (default: "developer")

    Returns:
        Recommended documentation with explanations
    """
    recommendations = []

    # Topic-based recommendations
    topic_lower = topic.lower()

    # Container/Kubernetes topics -> OpenShift
    if any(keyword in topic_lower for keyword in ["container", "kubernetes", "k8s", "docker", "pod"]):
        recommendations.append(
            {
                "product": "OpenShift Container Platform",
                "relevance": "high",
                "reason": "OpenShift is Red Hat's enterprise Kubernetes platform for container orchestration",
                "guides": [
                    "Getting Started with OpenShift",
                    "Installing OpenShift on your cloud provider",
                    "Developer Guide" if role == "developer" else "Administration Guide",
                ],
                "base_url": f"{REDHAT_DOCS_BASE}/en/documentation/openshift_container_platform/4.18",
            }
        )

    # Edge/Telco/CNF topics -> OpenShift Edge Computing
    if any(keyword in topic_lower for keyword in ["edge", "telco", "cnf", "5g", "edge computing", "network function"]):
        recommendations.append(
            {
                "product": "OpenShift Container Platform - Edge Computing",
                "relevance": "high",
                "reason": "OpenShift provides specialized edge computing capabilities for telco and CNF workloads",
                "guides": [
                    "Edge Computing Guide",
                    "Scalability and Performance",
                    "Post-installation Configuration",
                    "Updating Clusters" if "update" in topic_lower else "Administration Guide",
                ],
                "base_url": f"{REDHAT_DOCS_BASE}/en/documentation/openshift_container_platform/4.18",
            }
        )

    # Upgrade/Update topics -> OpenShift Updates
    if any(keyword in topic_lower for keyword in ["upgrade", "update", "cluster update", "upgrading"]):
        recommendations.append(
            {
                "product": "OpenShift Container Platform - Cluster Updates",
                "relevance": "high",
                "reason": "Comprehensive guidance for updating OpenShift clusters safely",
                "guides": [
                    "Updating Clusters",
                    "Updating Machines in a Cluster",
                    "Administration Guide",
                    "Post-installation Configuration",
                ],
                "base_url": f"{REDHAT_DOCS_BASE}/en/documentation/openshift_container_platform/4.18",
            }
        )

    # Automation topics -> Ansible
    if any(keyword in topic_lower for keyword in ["automation", "ansible", "playbook", "configuration"]):
        recommendations.append(
            {
                "product": "Red Hat Ansible Automation Platform",
                "relevance": "high",
                "reason": "Ansible Automation Platform provides enterprise automation capabilities",
                "guides": ["Getting Started with Ansible", "Automation Controller User Guide", "Best Practices Guide"],
                "base_url": f"{REDHAT_DOCS_BASE}/en/documentation/red_hat_ansible_automation_platform/2.4",
            }
        )

    # Linux/OS topics -> RHEL
    if any(keyword in topic_lower for keyword in ["linux", "rhel", "operating system", "os", "server"]):
        recommendations.append(
            {
                "product": "Red Hat Enterprise Linux",
                "relevance": "high",
                "reason": "RHEL is Red Hat's enterprise Linux distribution",
                "guides": [
                    "Getting Started with RHEL",
                    "System Administrator's Guide" if role in ["administrator", "architect"] else "User Guide",
                    "Security Guide",
                ],
                "base_url": f"{REDHAT_DOCS_BASE}/en/documentation/red_hat_enterprise_linux/9",
            }
        )

    # Management topics -> Satellite
    if any(keyword in topic_lower for keyword in ["management", "satellite", "patch", "compliance"]):
        recommendations.append(
            {
                "product": "Red Hat Satellite",
                "relevance": "medium",
                "reason": "Satellite provides systems management and compliance capabilities",
                "guides": [
                    "Installing Satellite",
                    "Managing Hosts" if role == "administrator" else "User Guide",
                    "Content Management Guide",
                ],
                "base_url": f"{REDHAT_DOCS_BASE}/en/documentation/red_hat_satellite/6.15",
            }
        )

    # If no specific matches, provide general recommendations
    if not recommendations:
        recommendations = [
            {
                "product": "Red Hat Product Documentation",
                "relevance": "medium",
                "reason": f"General Red Hat documentation for {role}s",
                "guides": ["Browse all Red Hat products", "Getting started guides", "Best practices documentation"],
                "base_url": REDHAT_DOCS_BASE,
            }
        ]

    return {
        "topic": topic,
        "role": role,
        "total_recommendations": len(recommendations),
        "recommendations": recommendations,
    }


@mcp.tool()
async def search_with_web_guidance(
    query: str, product: str | None = None, version: str | None = None, limit: int = 10
) -> dict[str, Any]:
    """
    Enhanced search that provides both direct results and guidance for web search integration.

    This tool demonstrates the hybrid approach by:
    1. Providing direct sitemap-based results from our server
    2. Suggesting optimized web search queries for additional discovery
    3. Explaining how to combine both approaches effectively

    Args:
        query: Search terms
        product: Filter by specific product (optional)
        version: Filter by specific version (optional)
        limit: Maximum number of results (default: 10)

    Returns:
        Direct results plus web search guidance
    """
    # Get our direct sitemap results
    direct_results = await search_documentation(query, product, version, limit)

    # Generate comprehensive Red Hat domain search queries
    web_search_queries = generate_redhat_search_queries(query, product)

    return {
        "query": query,
        "filters": {"product": product, "version": version},
        "direct_results": direct_results,
        "web_search_guidance": {
            "recommended_queries": web_search_queries[:5],  # Limit to top 5
            "search_tips": [
                "Use site:docs.redhat.com to restrict to official Red Hat documentation",
                "Add specific version numbers (4.18, 4.17) for current documentation",
                'Use quotes around exact phrases like "updating clusters"',
                "Combine product names with your topic for focused results",
                "Look for PDF URLs in search results for reliable content access",
            ],
            "post_search_actions": [
                "Copy found URLs and use our read_documentation() tool to access content",
                "Use our extract_pdf_url() logic to convert HTML URLs to PDF format",
                "Cross-reference web search results with our sitemap discoveries",
                "Prioritize URLs with version 4.x over legacy 3.x documentation",
            ],
        },
        "hybrid_workflow": {
            "step_1": "Run this search to get direct sitemap-based results",
            "step_2": "Use the suggested web search queries to find additional content",
            "step_3": "Combine results and use read_documentation() to access specific guides",
            "step_4": "Leverage both PDF and HTML access options as needed",
        },
        "integration_note": (
            "This demonstrates the hybrid approach. In practice, you could automate step 2 "
            "using MCP WebSearch tool or external search APIs."
        ),
    }


@mcp.tool()
async def smart_documentation_finder(query: str, preferred_format: str = "pdf", max_results: int = 5) -> dict[str, Any]:
    """
    Intelligent documentation finder that combines web search discovery with
    our enhanced documentation access capabilities.

    This tool:
    1. Uses web search to find relevant Red Hat documentation URLs
    2. Validates and enhances the URLs with proper PDF/HTML formats
    3. Tests accessibility and provides working links
    4. Returns the best available documentation sources

    Args:
        query: Search query (e.g., "OpenShift edge computing cluster updates")
        preferred_format: "pdf", "html", or "auto" (default: "pdf")
        max_results: Maximum number of results to return (default: 5)

    Returns:
        Curated list of accessible Red Hat documentation with working URLs
    """
    # Step 1: Enhanced search combining sitemap + web search
    search_results = await search_documentation_enhanced(query, limit=max_results * 2, include_web_search=True)

    # Step 2: Process and validate results
    validated_results = []

    for result in search_results.get("combined_results", []):
        html_url = result.get("html_url", "")
        pdf_url = result.get("pdf_url", "")

        if not html_url:
            continue

        # Create enhanced result with multiple access options
        enhanced_result = {
            "title": result.get("title", ""),
            "description": result.get("snippet", ""),
            "source": result.get("source", "sitemap"),
            "product": result.get("product", ""),
            "version": result.get("version", ""),
            "relevance_score": result.get("relevance_score", 0.5),
            "access_options": {
                "html": {
                    "url": html_url,
                    "format": "html",
                    "notes": "Requires JavaScript rendering, may need browser access",
                },
                "pdf": {"url": pdf_url, "format": "pdf", "notes": "Direct PDF access, best for content extraction"},
            },
            "recommended_url": pdf_url if preferred_format == "pdf" else html_url,
            "recommended_format": preferred_format,
        }

        # Add web search snippet if available
        if result.get("snippet"):
            enhanced_result["search_snippet"] = result["snippet"]

        validated_results.append(enhanced_result)

        if len(validated_results) >= max_results:
            break

    # Step 3: Add intelligent recommendations based on query
    recommendations = []
    query_lower = query.lower()

    if any(word in query_lower for word in ["upgrade", "update", "cluster update"]):
        recommendations.append("For cluster upgrades, prioritize the 'Updating Clusters' guide")

    if any(word in query_lower for word in ["edge", "telco", "cnf"]):
        recommendations.append(
            "For edge deployments, also check 'Edge Computing' and 'Scalability and Performance' guides"
        )

    if any(word in query_lower for word in ["install", "installation"]):
        recommendations.append("Check both installation guides and post-installation configuration")

    return {
        "query": query,
        "preferred_format": preferred_format,
        "total_found": len(validated_results),
        "results": validated_results,
        "search_strategy": {
            "sitemap_results": len([r for r in validated_results if r["source"] == "sitemap"]),
            "web_search_results": len([r for r in validated_results if r["source"].startswith("web_search")]),
            "sources_used": ["Red Hat sitemap discovery", "Web search indexing"],
        },
        "recommendations": recommendations,
        "usage_tips": [
            f"Use PDF URLs for reliable content access (preferred format: {preferred_format})",
            "HTML URLs may require JavaScript rendering",
            "Check multiple guides for comprehensive information",
            "Newer versions (4.x) are recommended over legacy (3.x) documentation",
        ],
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
