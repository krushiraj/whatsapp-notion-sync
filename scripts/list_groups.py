"""Connect to WhatsApp, print groups, then exit.

Usage:
    python scripts/list_groups.py                     # all groups
    python scripts/list_groups.py "Second brain"      # only groups in that community
"""

import signal
import sys

from neonize.client import NewClient
from neonize.events import ConnectedEv, event
from neonize.utils.jid import Jid2String

COMMUNITY_FILTER = sys.argv[1] if len(sys.argv) > 1 else None

client = NewClient("wa_session.db")


@client.event(ConnectedEv)
def on_connected(c: NewClient, _: ConnectedEv):
    if COMMUNITY_FILTER:
        all_groups = c.get_joined_groups()
        community = None
        for g in all_groups:
            if g.GroupName.Name == COMMUNITY_FILTER and g.GroupParent.ListFields():
                community = g
                break
        if not community:
            print(f"\nNo community named '{COMMUNITY_FILTER}' found. Your communities:")
            for g in all_groups:
                if g.GroupParent.ListFields():
                    print(f"  {g.GroupName.Name}")
            print()
            event.set()
            return

        subs = c.get_sub_groups(community.JID)
        print(f"\nGroups in '{COMMUNITY_FILTER}':\n")
        print(f"  {'Group Name':<40} JID")
        print(f"  {'-'*73}")
        for s in subs:
            print(f"  {s.GroupName.Name:<40} {Jid2String(s.JID)}")
    else:
        groups = c.get_joined_groups()
        print(f"\n{'Group Name':<40} JID")
        print("-" * 75)
        for g in groups:
            print(f"{g.GroupName.Name:<40} {Jid2String(g.JID)}")

    print()
    event.set()


signal.signal(signal.SIGINT, lambda *_: event.set())
client.connect()
event.wait()
