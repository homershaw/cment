"""Run the SCADA:            python -m scada [--config config.toml]
Add or change a user:      python -m scada adduser NAME --role operator"""
import argparse
import getpass
import logging
import sys

import uvicorn

from . import auth
from .config import load
from .engine import Engine
from .store import Store


def main():
    ap = argparse.ArgumentParser(description="Cement batch plant SCADA")
    ap.add_argument("--config", help="path to config.toml")
    sub = ap.add_subparsers(dest="cmd")
    au = sub.add_parser("adduser", help="add or update a user")
    au.add_argument("username")
    au.add_argument("--role", default="operator", choices=auth.ROLES)
    au.add_argument("--password", help="omit to be prompted")
    args = ap.parse_args()

    cfg = load(args.config)
    store = Store(cfg.db_path)

    if args.cmd == "adduser":
        pw = args.password or getpass.getpass(f"Password for {args.username}: ")
        try:
            auth.add_user(store, args.username, pw, args.role)
        except ValueError as e:
            sys.exit(str(e))
        print(f"User {args.username} saved with role {args.role}")
        return

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not store.q("SELECT 1 FROM users LIMIT 1"):
        logging.warning("No users yet: screens work, but batch control needs one. "
                        "Run: python -m scada adduser NAME --role operator")
    from .app import create_app
    app = create_app(cfg, store, Engine(cfg, store))
    print(f"SCADA on http://localhost:{cfg.web_port}  (PLC {cfg.plc_host}:{cfg.plc_port}, "
          f"control {'ENABLED' if cfg.control_enabled else 'disabled'})")
    uvicorn.run(app, host=cfg.web_host, port=cfg.web_port, log_level="warning")


if __name__ == "__main__":
    main()
