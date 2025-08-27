
#!/usr/bin/env python3
"""
Quick test runner for OpenStackRequestsClient (loads .env automatically if present).

Usage:
  # Either export env vars OR create a .env file (see .env.example)
  python test_openstack_client_requests.py <INSTANCE_ID> [--save result.json]
"""
import os
import sys
import json
import argparse
import logging

# Load .env if present
try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(), override=False)
except Exception:
    pass

from openstack_client_requests import OpenStackRequestsClient, OpenStackError

def env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")

def build_client() -> OpenStackRequestsClient:
    host = os.getenv("OS_HOST", "127.0.0.1")
    username = os.getenv("OS_USERNAME")
    password = os.getenv("OS_PASSWORD")
    project_id = os.getenv("OS_PROJECT_ID")
    user_domain = os.getenv("OS_USER_DOMAIN_NAME", "Default")
    verify = env_bool("OS_VERIFY_SSL", False)
    timeout = float(os.getenv("OS_REQUEST_TIMEOUT", "15.0"))

    missing = [k for k, v in [
        ("OS_USERNAME", username),
        ("OS_PASSWORD", password),
        ("OS_PROJECT_ID", project_id),
    ] if not v]
    if missing:
        print(f"Missing required env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(2)

    return OpenStackRequestsClient(
        host=host,
        username=username,
        password=password,
        project_id=project_id,
        user_domain=user_domain,
        verify=verify,
        timeout=timeout,
    )

def main():
    parser = argparse.ArgumentParser(description="Test OpenStackRequestsClient by fetching a server by ID.")
    parser.add_argument("instance_id", help="OpenStack server (instance) ID to fetch")
    parser.add_argument("--save", help="Optional path to save JSON output")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"),
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Logging level")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    client = build_client()
    try:
        result = client.get_server_composite(args.instance_id)
    except OpenStackError as e:
        print(json.dumps({"error": {"type": "OpenStackError", "message": str(e), "http_status": e.http_status, "details": e.details}}, indent=2, ensure_ascii=False))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": {"type": "UnexpectedError", "message": str(e), "http_status": None}}, indent=2, ensure_ascii=False))
        sys.exit(1)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if args.save:
        try:
            with open(args.save, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            print(f"Saved to {args.save}")
        except Exception as e:
            print(f"Failed to save to {args.save}: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
