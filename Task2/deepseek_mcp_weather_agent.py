#!/usr/bin/env python3
"""Minimal DeepSeek agent that calls the Chapter 4 weather tool through MCP."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import OpenAI


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SERVER = HERE / "src" / "main.py"
OUTPUT_DIR = HERE / "task2-output"
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
QUESTION = (
    "请查询 Shanghai, China 当前天气，并根据温度、降水和风速给出一句简短的出行建议。"
)


def load_deepseek_key() -> str:
    """Load a key without printing or copying it into experiment artifacts."""
    if os.getenv("DEEPSEEK_API_KEY"):
        return os.environ["DEEPSEEK_API_KEY"]
    for path in (REPO / ".env", REPO / "chapter1" / "context" / ".env"):
        value = dotenv_values(path).get("DEEPSEEK_API_KEY") if path.exists() else None
        if value:
            return value
    raise RuntimeError("未找到 DEEPSEEK_API_KEY，请写入仓库 .env 或 chapter1/context/.env")


def tool_schema(tool: Any) -> dict[str, Any]:
    data = tool.model_dump(by_alias=True, exclude_none=True, mode="json")
    return {
        "type": "function",
        "function": {
            "name": data["name"],
            "description": data.get("description", ""),
            "parameters": data.get("inputSchema", {"type": "object", "properties": {}}),
        },
    }


def result_text(result: Any) -> str:
    parts = []
    for item in result.content:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


async def run() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    api_key = load_deepseek_key()
    llm = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER)],
        env=os.environ.copy(),
    )

    receipt: dict[str, Any] = {
        "experiment": "DeepSeek + MCP Weather Tool",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "question": QUESTION,
        "transport": "mcp-stdio",
        "mcp_sdk_version": version("mcp"),
    }

    async with Client(stdio_client(parameters)) as mcp:
        listed = await mcp.list_tools()
        weather = next(tool for tool in listed.tools if tool.name == "weather")
        receipt["mcp_protocol_version"] = mcp.protocol_version
        receipt["mcp_server"] = mcp.server_info.name if mcp.server_info else None
        receipt["listed_tool_count"] = len(listed.tools)

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "你是一个谨慎的天气助手。凡是问题涉及当前天气，必须调用 weather 工具，"
                    "不得凭记忆猜测。拿到工具结果后再用中文回答，并说明数据来源。"
                ),
            },
            {"role": "user", "content": QUESTION},
        ]

        first = llm.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=[tool_schema(weather)],
            tool_choice="auto",
            temperature=0,
        )
        decision = first.choices[0].message
        if not decision.tool_calls:
            raise RuntimeError(f"DeepSeek 未选择工具，返回内容：{decision.content!r}")

        call = decision.tool_calls[0]
        arguments = json.loads(call.function.arguments)
        if call.function.name != "weather":
            raise RuntimeError(f"DeepSeek 选择了意外工具：{call.function.name}")

        print("[1/4] 判断：问题涉及实时天气，需要外部数据")
        print(f"[2/4] Tool Calling：{call.function.name}({json.dumps(arguments, ensure_ascii=False)})")

        tool_result = await mcp.call_tool(call.function.name, arguments=arguments)
        observation = result_text(tool_result)
        if tool_result.is_error:
            raise RuntimeError(f"MCP 工具调用失败：{observation}")
        observation_data = json.loads(observation)
        if not observation_data.get("success"):
            raise RuntimeError(f"天气工具业务调用失败：{observation}")
        print(f"[3/4] MCP 返回：{observation}")

        messages.append(decision.model_dump(exclude_none=True))
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": observation,
            }
        )
        final = llm.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0,
        ).choices[0].message.content
        print(f"[4/4] 最终回答：{final}")

        receipt.update(
            {
                "decision": "call_tool",
                "tool_name": call.function.name,
                "tool_arguments": arguments,
                "tool_is_error": tool_result.is_error,
                "tool_result": observation_data,
                "final_answer": final,
                "status": "passed",
            }
        )

    receipt_path = OUTPUT_DIR / "weather-agent-receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[PASS] 完整 Tool Calling 流程已跑通，证据：{receipt_path}")


if __name__ == "__main__":
    asyncio.run(run())
