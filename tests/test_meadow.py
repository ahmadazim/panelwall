import time

import numpy as np

from panelwall.channels.meadow import MeadowChannel, cat_sprite, kuromi_sprite, WORLD_W, CAT_X
from panelwall.framebuffer import Frame, W, H


def _run(ch, seconds, dt=0.05):
    for _ in range(int(seconds / dt)):
        ch.tick(dt)


def test_sprites_build_and_differ_per_step():
    walks = [np.asarray(cat_sprite("walk", s)) for s in range(4)]
    assert all(w.shape == (26, 44, 4) for w in walks)
    assert (walks[0] != walks[1]).any() and (walks[0] == walks[2]).all()           # 4-step cycle, 0 == 2
    sit, back = np.asarray(cat_sprite("sit", 0)), np.asarray(cat_sprite("sit", 0, True))
    assert (sit != back).any()
    k = [np.asarray(kuromi_sprite(s)) for s in range(4)]
    assert k[0].shape == (24, 22, 4) and (k[0] != k[1]).any()
    # brand check: Kuromi is mostly black and white with some pink; the cat is mostly orange
    kp = k[0][k[0][:, :, 3] > 0][:, :3]
    assert (kp.max(axis=1) < 40).mean() > 0.3 and ((kp[:, 0] > 200) & (kp[:, 1] < 150)).any()
    cp = walks[0][walks[0][:, :, 3] > 0][:, :3]
    assert ((cp[:, 0] > 180) & (cp[:, 2] < 80)).mean() > 0.5


def test_is_deterministic_and_loops():
    a, b = MeadowChannel(seed=7), MeadowChannel(seed=7)
    for ch in (a, b):
        _run(ch, 12.0)
    fa, fb = Frame(), Frame()
    a.render(fa)
    b.render(fb)
    assert (fa.to_array() == fb.to_array()).all()
    assert 0 <= a.scroll < WORLD_W
    _run(a, 60.0)
    assert 0 <= a.scroll < WORLD_W                                                   # wraps, never grows


def test_state_machine_visits_every_pose():
    ch = MeadowChannel(seed=7)
    seen = set()
    for _ in range(int(120 / 0.05)):
        ch.tick(0.05)
        seen.add((ch.state, ch.look_back))
    assert {("walk", False), ("sit", False), ("sit", True)} <= seen
    assert ch.priority() == 2 and ch.status()["state"] in ("walk", "sit")


def test_render_is_cheap_and_fills_the_frame():
    ch = MeadowChannel()
    f = Frame()
    _run(ch, 2.0)
    ch.render(f)
    arr = f.to_array()
    assert arr.shape == (H, W, 3) and (arr.max(axis=2) > 0).mean() > 0.95            # sky and grass cover it
    assert arr[0, 0].tolist() != arr[H - 1, 0].tolist()                               # sky != grass
    t0 = time.perf_counter()
    for _ in range(50):
        ch.tick(0.05)
        f.clear()
        ch.render(f)
    assert (time.perf_counter() - t0) / 50 < 0.01                                      # < 10 ms/frame
    # the cat is where the scene says it is: orange pixels around CAT_X on the ground
    patch = arr[H - 26:H, CAT_X:CAT_X + 44]
    assert ((patch[:, :, 0] > 180) & (patch[:, :, 2] < 80)).sum() > 100
