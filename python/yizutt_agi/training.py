import argparse
import json
import time
import uuid
from pathlib import Path
from typing import Any

from .memory import WorkingMemory


def prepare_lora_job(
    memory_path: str,
    output_dir: str,
    base_model: str,
    adapter_name: str,
    limit: int = 2000,
    min_score: float = 0.65,
) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    memory = WorkingMemory(memory_path)
    try:
        examples = [
            item
            for item in memory.training_examples(limit=limit, accepted_only=True)
            if float(item.get("quality_score", 0.0)) >= min_score
        ]
    finally:
        memory.close()

    job_id = f"lora-{uuid.uuid4()}"
    dataset_path = out / "dataset.jsonl"
    manifest_path = out / "lora_job.json"
    created_at = int(time.time())

    with dataset_path.open("w", encoding="utf-8") as fh:
        for item in examples:
            row = {
                "instruction": item["task"],
                "input": "",
                "output": item["answer"],
                "metadata": {
                    "training_example_id": item["id"],
                    "session_id": item["session_id"],
                    "quality_score": item["quality_score"],
                    "created_at": item["created_at"],
                },
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    manifest = {
        "job_id": job_id,
        "status": "prepared",
        "base_model": base_model,
        "adapter_name": adapter_name,
        "dataset_path": str(dataset_path),
        "dataset_format": "jsonl:instruction,input,output,metadata",
        "example_count": len(examples),
        "min_score": min_score,
        "created_at": created_at,
        "next_step": (
            "Run your LoRA trainer against dataset_path, then update this manifest "
            "with status=running/completed/failed and adapter artifact paths."
        ),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare LoRA fine-tuning job artifacts from Yizutt training examples.")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare-lora", help="Export accepted training examples into a LoRA-ready JSONL dataset.")
    prepare.add_argument("--memory-path", default=".yizutt/memory/work.sqlite3")
    prepare.add_argument("--output-dir", default=".yizutt/training/lora/latest")
    prepare.add_argument("--base-model", required=True)
    prepare.add_argument("--adapter-name", default="yizutt-adapter")
    prepare.add_argument("--limit", type=int, default=2000)
    prepare.add_argument("--min-score", type=float, default=0.65)
    args = parser.parse_args()

    if args.command == "prepare-lora":
        manifest = prepare_lora_job(
            memory_path=args.memory_path,
            output_dir=args.output_dir,
            base_model=args.base_model,
            adapter_name=args.adapter_name,
            limit=args.limit,
            min_score=args.min_score,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
