#!/usr/bin/env python3
"""Run Chapter 10 experiment 10-1 with a real DeepSeek model.

The Chapter 10 orchestrator and role/tool implementations are copied into src/.
Set DEEPSEEK_API_KEY before running. The optional endpoint/Host settings allow
the same official DeepSeek API to work through a local network proxy.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))

from orchestrator import MultiRoleOrchestrator  # noqa: E402


TASK = (
    "请写一个 Python 脚本，计算从 0、1 开始的斐波那契数列前 20 项及其总和。"
    "请让合适的角色用 execute_python 真正运行代码取得结果，"
    "再由写作角色用一句话向非技术读者解释结果，最后交回前台分诊收尾。"
)


def main() -> int:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise SystemExit("缺少 DEEPSEEK_API_KEY，请在本机环境变量中设置")

    base_url = os.environ.get("TASK5_DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    host = os.environ.get("TASK5_DEEPSEEK_HOST")
    headers = {"Host": host} if host else None
    client = OpenAI(
        api_key=key,
        base_url=base_url,
        default_headers=headers,
        timeout=45,
        max_retries=2,
    )
    provider_receipts: list[dict] = []

    def record_provider(item: dict) -> None:
        response = item["response"]
        provider_receipts.append(
            {
                "role": item["role"],
                "response_id": item["response_id"],
                "response_model": item["response_model"],
                "duration_seconds": item["duration_seconds"],
                "usage": response.get("usage"),
                "tool_names": [
                    call.get("function", {}).get("name")
                    for call in (response.get("choices", [{}])[0].get("message", {}).get("tool_calls") or [])
                ],
            }
        )

    agent = MultiRoleOrchestrator(
        client=client,
        model="deepseek-chat",
        max_steps=12,
        verbose=True,
        start_role="triage",
        provider_receipt_sink=record_provider,
    )
    print("Task5 / 实验 10-1：多角色移交，模型 deepseek-chat", flush=True)
    print("任务：", TASK, flush=True)
    answer = agent.run(TASK)

    chain = ([agent.handoffs[0].from_role] + [h.to_role for h in agent.handoffs]) if agent.handoffs else []
    tool_messages = [str(m.get("content", "")) for m in agent.history if m.get("role") == "tool"]
    executed = any(role == "coding" and kind == "tool" and detail == "execute_python" for role, kind, detail in agent.activity)
    execution_result = next((m for m in tool_messages if "10945" in m), "")
    gates = {
        "triage_handed_off_to_coding": any(h.from_role == "triage" and h.to_role == "coding" for h in agent.handoffs),
        "coding_executed_python": executed,
        "python_result_is_10945": bool(execution_result),
        "writing_role_participated": "writing" in chain,
        "final_answer_mentions_10945": "10945" in answer,
        "finished_before_step_limit": not agent.terminated_by_limit,
        "provider_responses_recorded": len(provider_receipts) == len(agent.api_calls) > 0,
    }
    status = "passed" if all(gates.values()) else "failed"
    receipt = {
        "experiment": "Chapter 10 / 10-1 multi-role-transfer, coding scenario",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider": "DeepSeek official API",
        "requested_model": "deepseek-chat",
        "connection_route": "official API via CloudFront" if host else "official API direct",
        "task": TASK,
        "handoff_chain": chain,
        "handoffs": [vars(h) for h in agent.handoffs],
        "activity": [{"role": role, "kind": kind, "detail": detail} for role, kind, detail in agent.activity],
        "provider_receipts": provider_receipts,
        "api_calls": agent.api_calls,
        "history": agent.history,
        "steps_used": agent.steps_used,
        "terminated_by_limit": agent.terminated_by_limit,
        "final_answer": answer,
        "acceptance_gates": gates,
        "status": status,
    }
    output = HERE / "evidence" / "run-receipt.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n验收结果：", json.dumps(gates, ensure_ascii=False), flush=True)
    print(f"[{status.upper()}] 证据已保存：{output}", flush=True)
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
