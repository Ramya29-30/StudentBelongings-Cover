import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("evalmod", Path(__file__).resolve().parents[2] / "ai_training" / "evaluate_damage_model.py")
ev = importlib.util.module_from_spec(spec); spec.loader.exec_module(ev)


def test_iou_and_matching_metrics():
    assert ev.iou((0, 0, .5, .5), (0, 0, .5, .5)) == 1 and ev.iou((0, 0, .1, .1), (.5, .5, .6, .6)) == 0
    r = ev.score([("a", .9, (0, 0, .5, .5)), ("a", .8, (.6, .6, .9, .9)), ("b", .7, (0, 0, .2, .2))], [("a", (0, 0, .5, .5)), ("a", (.1, .1, .5, .5)), ("b", (.7, .7, .9, .9))])
    assert r["a"] == [1, 1, 1] and r["b"] == [0, 1, 1]  # [tp, fp, fn]
