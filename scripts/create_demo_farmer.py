"""Create one farmer, one farm and one node in the configured database, for a
demo on a fresh install (SEED_DEMO is off by default, so a new database has no
login).

    set GAGE_DEMO_PASSWORD=<a password of your choice>      (Windows cmd)
    $env:GAGE_DEMO_PASSWORD = "<a password>"                 (PowerShell)
    export GAGE_DEMO_PASSWORD=<a password>                   (bash)
    python scripts/create_demo_farmer.py [--phone 9876543210] [--name "Ravi"]

The password is read from GAGE_DEMO_PASSWORD (never from the command line, so
it does not land in shell history). The node's API key is generated, printed
ONCE, and stored only as a hash: put it in the ESP32 firmware / node app now.
Running it again for the same phone changes nothing and prints no key.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phone", default="9876543210")
    ap.add_argument("--name", default="Demo Farmer")
    ap.add_argument("--language", default="kn", choices=["kn", "en"])
    ap.add_argument("--farm", default="Demo Farm")
    ap.add_argument("--village", default="Mandya")
    ap.add_argument("--node-id", default="field-node-1")
    args = ap.parse_args()

    password = os.environ.get("GAGE_DEMO_PASSWORD", "")
    if len(password) < 8:
        print("Set GAGE_DEMO_PASSWORD to a password of at least 8 characters first.",
              file=sys.stderr)
        return 2

    from sqlalchemy import select

    from backend.core.security import generate_api_key, hash_node_key, hash_password
    from backend.database import SessionLocal, init_db
    from backend.models import Farm, Farmer, Node, NodeHealth, _now

    init_db()   # creates the tables on a fresh database
    with SessionLocal() as db:
        if db.execute(select(Farmer).where(Farmer.phone == args.phone)).scalar_one_or_none():
            print(f"A farmer with phone {args.phone} already exists; nothing changed.")
            return 0
        if db.get(Node, args.node_id) is not None:
            print(f"Node id {args.node_id} is already registered; choose another --node-id.",
                  file=sys.stderr)
            return 2
        farmer = Farmer(phone=args.phone, password_hash=hash_password(password),
                        name=args.name, language=args.language)
        db.add(farmer)
        db.flush()
        farm = Farm(farmer_id=farmer.id, name=args.farm, crop_type="sugarcane",
                    village=args.village)
        db.add(farm)
        db.flush()
        key = generate_api_key()
        db.add(Node(id=args.node_id, farm_id=farm.id, name="Field node 1",
                    api_key=hash_node_key(key)))
        db.add(NodeHealth(node_id=args.node_id, status="offline", last_seen=_now()))
        farm_id = farm.id
        db.commit()

    print(f"Created farmer {args.phone} ({args.name}), farm '{args.farm}' (id {farm_id}), "
          f"node '{args.node_id}'.")
    print("Log in with that phone number and the password from GAGE_DEMO_PASSWORD.")
    print(f"NODE API KEY (shown once, store it now): {key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
