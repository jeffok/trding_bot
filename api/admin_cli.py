# admin_cli.py
import argparse
import requests
import json
import sys
import os
from datetime import datetime

# 默认配置，可从环境变量读取
API_URL = os.getenv("API_URL", "http://localhost:8000")
# 注意：CLI 客户端需要知道 Token，实际部署时可存放在 ~/.asv8_token 或环境变量
ADMIN_TOKEN = os.getenv("API_SECRET", "your_secret_here")

def call_api(endpoint, payload):
    headers = {
        "Authorization": f"Bearer {ADMIN_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        resp = requests.post(f"{API_URL}{endpoint}", json=payload, headers=headers, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"❌ API Call Failed: {e}")
        try:
            print(f"Detail: {resp.text}")
        except:
            pass
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Alpha-Sniper V8 Admin CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Common args
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--actor", required=True, help="Your name/ID")
    common_parser.add_argument("--reason_code", required=True, help="Short code (e.g., RISK_HIGH)")
    common_parser.add_argument("--reason", required=True, help="Human readable reason")

    # Command: status
    parser_status = subparsers.add_parser("status", help="Get system health")

    # Command: halt
    parser_halt = subparsers.add_parser("halt", parents=[common_parser], help="Emergency HALT")

    # Command: resume
    parser_resume = subparsers.add_parser("resume", parents=[common_parser], help="Resume trading")

    # Command: set (Config)
    parser_set = subparsers.add_parser("set", parents=[common_parser], help="Set config")
    parser_set.add_argument("key", help="Config key")
    parser_set.add_argument("value", help="Config value (string/int)")

    args = parser.parse_args()

    if args.command == "status":
        try:
            resp = requests.get(f"{API_URL}/health", timeout=2)
            print(json.dumps(resp.json(), indent=2))
        except Exception as e:
            print(f"❌ Error: {e}")

    elif args.command in ["halt", "resume"]:
        endpoint = f"/admin/{args.command}"
        payload = {
            "actor": args.actor,
            "reason_code": args.reason_code,
            "reason": args.reason
        }
        res = call_api(endpoint, payload)
        print(f"✅ Success: {res}")

    elif args.command == "set":
        endpoint = "/admin/update_config"
        payload = {
            "actor": args.actor,
            "reason_code": args.reason_code,
            "reason": args.reason,
            "params": {"key": args.key, "value": args.value}
        }
        res = call_api(endpoint, payload)
        print(f"✅ Success: {res}")

    else:
        parser.print_help()

if __name__ == "__main__":
    main()