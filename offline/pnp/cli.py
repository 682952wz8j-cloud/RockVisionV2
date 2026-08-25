from __future__ import annotations

from pathlib import Path

from .opencv_cli import load_pinned_pnp, run_self_test
from .pipeline import PnPPipelineError, run_session


def run_pnp(args, root: Path) -> int:
    if args.self_test:
        payload = run_self_test(root)
        print(f"OpenCV: {payload.get('cvVersion')}")
        print(f"Convention self-test: {'PASS' if payload.get('pass') else 'FAIL'}")
        correct = payload.get("correct") or {}
        print(f"rotationDeg={correct.get('rotationDeg')} centerError={correct.get('centerError')} reprojMedian={correct.get('reprojMedian')}")
        return 0 if payload.get("pass") else 1
    if args.session:
        try:
            payload = run_session(root, Path(args.session), wall_id=args.wall_id)
        except PnPPipelineError as exc:
            print(exc)
            return 1
        print(f"Frames: {payload.get('frameCount')}")
        if payload.get("errors"):
            for err in payload["errors"]:
                print("ERROR:", err)
            return 1
        return 0
    runtime = load_pinned_pnp(root)
    print(f"OpenCV: {runtime.get('cvVersion')}")
    print(f"rv_pnp: {runtime.get('cli')}")
    print("Pass --self-test or --session samples.jsonl")
    return 0
