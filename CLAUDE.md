# CLAUDE.md — panelwall

**Read `HANDOFF.md` in full before doing anything.** It contains the complete project state,
hardware inventory, Pi configuration, protocol details, verified-vs-unverified facts, the
bring-up procedure, and the mistakes already made.

## Working rules (from the user)

- Verify before answering. Never present an inference as a fact. If it can be checked with a
  command, check it. If it can't, say "I'm inferring".
- The user is a strong software engineer with **zero hardware background**. Explain hardware by
  analogy to software/systems; no jargon without a one-line definition.
- Be concise. Recommend, don't list options, when a decision is a judgment call.
- After any change to a channel's layout, render it (`python -m panelwall demo --no-window
  --seconds 1`) and **look at `sim.png`** before declaring it done. Text collisions are only
  visible that way.

## Quick commands

```bash
source .venv/bin/activate            # NOT the conda `tf` env
python -m panelwall demo             # fixture data, live window (needs pygame)
python -m panelwall run              # live adsb.lol data around CONFIG.location
python -m panelwall test             # panel test pattern
python -m panelwall probe            # raw API JSON
python -m panelwall probe --routes AAL2570 JBU1287   # raw routeset reply (open issue)
python -m pytest -q
# on the Pi:
sudo python3 -m panelwall test --sink colorlight
sudo python3 -m panelwall run  --sink colorlight
```

## Invariants

- Display is 256×64 (8 × P5 64×32 panels, 4 wide × 2 tall). Everything assumes this.
- Draw text only via `Frame.text*` (cached). `frame.draw.text` directly costs ~1.4 ms/call.
- Network I/O only in background threads; `render()` reads snapshots.
- The Colorlight architecture is decided. Don't propose switching to a HAT.
- Packet layout in `sinks/colorlight.py` is covered by `tests/test_colorlight.py`; change both.
