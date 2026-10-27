import time

import numpy as np

from panelwall.channels.meadow import MeadowChannel, cat_sprite, kuromi_sprite, WORLD_W, CAT_X, CAT_W, CAT_H, KUROMI_W, KUROMI_H
from panelwall.framebuffer import Frame, W, H


def _run(ch, seconds, dt=0.05):
    for _ in range(int(seconds / dt)):
        ch.tick(dt)


def test_sprites_build_and_differ_per_step():
    walks = [np.asarray(cat_sprite("walk", s)) for s in range(4)]
    assert all(w.shape == (CAT_H, CAT_W, 4) for w in walks)
    assert (walks[0] != walks[1]).any() and (walks[0] == walks[2]).all()           # 4-step cycle, 0 == 2
    sit, back = np.asarray(cat_sprite("sit", 0)), np.asarray(cat_sprite("sit", 0, True))
    assert (sit != back).any()
    k = [np.asarray(kuromi_sprite(s)) for s in range(4)]
    assert k[0].shape == (KUROMI_H, KUROMI_W, 4) and (k[0] != k[1]).any()
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
    from datetime import datetime
    ch = MeadowChannel(weather="sun", now=datetime(2026, 9, 15, 13))   # daylight: the cat is at full colour
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
    patch = arr[H - CAT_H:H, CAT_X:CAT_X + CAT_W]
    assert ((patch[:, :, 0] > 180) & (patch[:, :, 2] < 80)).sum() > 200


def test_scene_state_sun_arc_east_left_west_right():
    from datetime import datetime
    from panelwall.channels.meadow_sky import scene_state
    sr, ss = datetime(2026, 9, 15, 6, 41), datetime(2026, 9, 15, 19, 9)
    dawn = scene_state(datetime(2026, 9, 15, 6, 50), sr, ss, "sun")
    noon = scene_state(datetime(2026, 9, 15, 12, 55), sr, ss, "sun")
    dusk = scene_state(datetime(2026, 9, 15, 19, 0), sr, ss, "sun")
    night = scene_state(datetime(2026, 9, 15, 1, 0), sr, ss, "sun")
    assert not dawn.night and dawn.sun_x < 40 and 0 < dawn.e < 0.1                 # just risen, on the left
    assert noon.sun_x > 120 and noon.sun_x < 136 and noon.e > 0.99 and noon.sun_y < 8
    assert dusk.sun_x > 216 and 0 < dusk.e < 0.1                                   # about to set, on the right
    assert night.night and night.e < -0.5 and night.light <= 0.35
    assert noon.light == 1.0 and dawn.light < noon.light
    # weather darkens and hides the sun
    rain = scene_state(datetime(2026, 9, 15, 12, 55), sr, ss, "rain")
    assert rain.cover > 0.8 and rain.light < noon.light
    assert scene_state(datetime(2026, 9, 15, 12, 0), None, None, "sun").e > 0.9    # defaults when no forecast
    assert scene_state(datetime(2026, 9, 15, 12, 0), sr, ss, "bogus").weather == "cloud"


def test_every_sky_renders_deterministically():
    from datetime import datetime
    seen = {}
    for weather in ("sun", "partly", "cloud", "fog", "rain", "snow", "storm"):
        for hour in (3, 6.8, 13, 18.9, 22):
            ch = MeadowChannel(weather=weather, now=datetime(2026, 9, 15, int(hour), int(hour % 1 * 60)))
            _run(ch, 1.0)
            f = Frame()
            ch.render(f)
            arr = f.to_array()
            assert arr.shape == (H, W, 3)
            seen[(weather, hour)] = arr.copy()
    assert (seen[("sun", 13)] != seen[("sun", 22)]).any()                           # day vs night differ
    assert seen[("sun", 22)][:20].mean() < seen[("sun", 13)][:20].mean()           # night sky is darker
    assert (seen[("rain", 13)] != seen[("sun", 13)]).any()
    # same inputs -> same picture
    a, b = MeadowChannel(weather="snow", now=datetime(2026, 9, 15, 13)), MeadowChannel(weather="snow", now=datetime(2026, 9, 15, 13))
    _run(a, 2.0)
    _run(b, 2.0)
    fa, fb = Frame(), Frame()
    a.render(fa)
    b.render(fb)
    assert (fa.to_array() == fb.to_array()).all()


def test_meadow_uses_the_forecast_feed_and_registers_for_polling():
    import json
    from pathlib import Path
    from panelwall.data.openmeteo import ForecastFeed
    fx = json.loads((Path(__file__).resolve().parent.parent / "fixtures" / "openmeteo.json").read_text())
    feed = ForecastFeed(static=fx)
    ch = MeadowChannel(forecast=feed)
    assert ch in feed.users
    st = ch.scene()
    assert st.weather == "sun"                                                      # fixture current code 0
    assert ch.status()["sky"] == "sun"
