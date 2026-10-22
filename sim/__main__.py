"""Run the simulated S7-1500:  python -m sim [--port 102] [--auto 60] [--faults]"""
import argparse
import logging
import time

from .plant import Plant
from .server import PlcServer


def main():
    ap = argparse.ArgumentParser(description="Simulated batch plant S7-1500 (S7 protocol)")
    ap.add_argument("--port", type=int, default=102, help="TCP port (S7 default 102)")
    ap.add_argument("--auto", type=float, default=60.0, help="start a batch after N idle seconds (0 = off)")
    ap.add_argument("--faults", action="store_true", help="inject tolerance faults and air-pressure dips")
    ap.add_argument("--speed", type=float, default=1.0, help="simulation speed multiplier")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")

    server = PlcServer()
    plant = Plant(server, auto_every=args.auto, faults=args.faults)
    server.start(tcp_port=args.port)
    print(f"Simulated S7-1500 on port {args.port} (rack 0, slot 1). Auto batch every {args.auto:g} s idle"
          f"{', faults on' if args.faults else ''}. Ctrl+C to stop.")
    dt = 0.1
    try:
        while True:
            plant.step(dt * args.speed)
            time.sleep(dt)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        server.destroy()


if __name__ == "__main__":
    main()
