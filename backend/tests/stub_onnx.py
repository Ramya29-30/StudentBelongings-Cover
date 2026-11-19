"""Builds a tiny STUB ONNX detector for tests. It ignores its input and always reports ONE fixed detection.

It exists only to test model loading, class-name metadata, the output layout and the verification pipeline through the real onnxruntime.
It is NOT a damage model and says nothing about accuracy: never copy it into backend/models.
"""
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper

CLASSES = ["Cracked screen", "Broken display", "Damaged body", "Camera lens damage", "Damaged keyboard", "Broken hinge"]


def build(path: Path, class_idx: int = 0, score: float = 0.9, box=(320.0, 320.0, 100.0, 100.0), names=None, embed_names: bool = True, nc: int | None = None) -> Path:
    names = CLASSES if names is None else names
    nc = len(names) if nc is None else nc
    n = 8400
    out = np.zeros((1, 4 + nc, n), np.float32)
    out[0, 0:4, 0] = box  # cx, cy, w, h in the 640x640 letterboxed frame
    out[0, 4 + class_idx, 0] = score
    node = helper.make_node("Constant", [], ["output0"], value=helper.make_tensor("v", TensorProto.FLOAT, out.shape, out.flatten().tolist()))
    graph = helper.make_graph([node], "stub", [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 640, 640])],
                              [helper.make_tensor_value_info("output0", TensorProto.FLOAT, list(out.shape))])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    if embed_names:
        for k, v in (("names", str({i: nm for i, nm in enumerate(names)})), ("imgsz", "[640, 640]")):
            p = model.metadata_props.add(); p.key, p.value = k, v
    onnx.save(model, str(path))
    return path
