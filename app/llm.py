from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class LlmError(Exception):
    """Raised when LLM enrichment fails."""


@dataclass
class LlmConfig:
    enabled: bool = False
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.2


def enrich_analysis_with_llm(
    analysis: dict[str, Any],
    materials: list[dict[str, Any]],
    config: LlmConfig,
) -> dict[str, Any]:
    if not config.enabled:
        analysis["llm"] = {"enabled": False, "status": "skipped"}
        return analysis
    validate_config(config)

    prompt = build_prompt(analysis, materials)
    payload = chat_completion(config, prompt)
    merge_llm_payload(analysis, payload, config)
    return analysis


def validate_config(config: LlmConfig) -> None:
    if not config.base_url.strip():
        raise LlmError("LLM baseURL 不能为空。")
    if not config.api_key.strip():
        raise LlmError("LLM APIKEY 不能为空。")
    if not config.model.strip():
        raise LlmError("LLM model 不能为空。")


def completion_endpoint(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if not value:
        raise LlmError("LLM baseURL 不能为空。")
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LlmError("LLM baseURL 必须是 http/https 地址。")
    if value.endswith("/chat/completions"):
        return value
    return f"{value}/chat/completions"


def chat_completion(config: LlmConfig, prompt: str) -> dict[str, Any]:
    endpoint = completion_endpoint(config.base_url)
    request_payload = {
        "model": config.model.strip(),
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是严谨的中文课程复习分析助手。请只基于用户提供的课堂文字、"
                    "老师提示和往年题证据判断，不要编造考试范围。只输出 JSON。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": config.temperature,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[-800:]
        raise LlmError(f"LLM 请求失败：HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise LlmError(f"LLM 请求失败：{exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise LlmError("LLM 返回的不是 JSON 响应。") from exc

    try:
        content = response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmError("LLM 响应缺少 choices[0].message.content。") from exc
    return parse_json_content(content)


def parse_json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1)
    elif not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LlmError("LLM 没有返回可解析的 JSON。") from exc
    if not isinstance(payload, dict):
        raise LlmError("LLM JSON 顶层必须是对象。")
    return payload


def build_prompt(analysis: dict[str, Any], materials: list[dict[str, Any]]) -> str:
    source_text = build_source_pack(materials)
    rule_topics = [
        {
            "name": topic.get("name"),
            "importance": topic.get("importance"),
            "score": topic.get("score"),
            "teacher_mentions": topic.get("teacher_mentions"),
            "exam_hits": topic.get("exam_hits"),
            "teacher_cues": topic.get("teacher_cues", [])[:6],
            "question_types": topic.get("question_types", [])[:6],
            "evidence": topic.get("evidence", [])[:3],
            "exam_evidence": topic.get("exam_evidence", [])[:3],
        }
        for topic in analysis.get("topics", [])[:30]
    ]
    return (
        "请基于下面资料增强期末复习判断。\n"
        "目标：总结老师画的期末重点、考题暗示、知识点重要程度，并结合往年题判断。\n\n"
        "请输出严格 JSON，格式如下：\n"
        "{\n"
        '  "summary": "100字以内总评",\n'
        '  "topic_updates": [\n'
        "    {\n"
        '      "name": "知识点名称",\n'
        '      "importance": "A|B|C",\n'
        '      "score_delta": 0,\n'
        '      "reason": "为什么重要，必须引用课堂或往年题证据",\n'
        '      "teacher_hint": "老师暗示或强调方式",\n'
        '      "exam_hint": "可能题型或命题方向",\n'
        '      "review_action": "具体复习动作"\n'
        "    }\n"
        "  ],\n"
        '  "exam_hints": ["考题暗示1"],\n'
        '  "study_plan": ["复习动作1"]\n'
        "}\n\n"
        "评分要求：A=必须优先复习；B=第二轮复习；C=浏览复习。"
        "如果证据不足，请降低重要度并写明原因。不要输出 JSON 之外的文字。\n\n"
        f"课程：{analysis.get('course')}\n"
        f"规则分析候选知识点：{json.dumps(rule_topics, ensure_ascii=False)}\n\n"
        f"资料摘录：\n{source_text}"
    )


def build_source_pack(materials: list[dict[str, Any]], limit: int = 22000) -> str:
    sections: list[str] = []
    used = 0
    for material in materials:
        text = (material.get("transcript") or material.get("extracted_text") or "").strip()
        if not text:
            continue
        name = material.get("original_name", "material")
        kind = material.get("kind", "")
        chunk = compact_text(text)
        remaining = limit - used
        if remaining <= 0:
            break
        if len(chunk) > remaining:
            chunk = chunk[:remaining]
        section = f"\n--- {name} [{kind}] ---\n{chunk}"
        sections.append(section)
        used += len(section)
    return "\n".join(sections) if sections else "无可用文本。"


def compact_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
    cue_pattern = re.compile("重点|重要|考试|期末|常考|必考|会考|注意|掌握|易错|题型|证明|计算")
    cue_lines = [line for line in lines if cue_pattern.search(line)]
    selected = cue_lines[:120]
    if len("\n".join(selected)) < 2500:
        selected.extend(lines[:80])
    deduped = list(dict.fromkeys(selected))
    return "\n".join(deduped)[:8000]


def merge_llm_payload(analysis: dict[str, Any], payload: dict[str, Any], config: LlmConfig) -> None:
    topic_updates = payload.get("topic_updates") or []
    if not isinstance(topic_updates, list):
        raise LlmError("LLM JSON 中 topic_updates 必须是数组。")

    topics = analysis.setdefault("topics", [])
    topic_index = {topic_key(topic.get("name", "")): topic for topic in topics}
    for update in topic_updates[:40]:
        if not isinstance(update, dict):
            continue
        name = str(update.get("name") or "").strip()
        if not name:
            continue
        key = topic_key(name)
        topic = topic_index.get(key) or find_near_topic(topics, name)
        if topic is None:
            topic = {
                "name": name,
                "importance": normalize_importance(update.get("importance")),
                "score": 0,
                "teacher_mentions": 0,
                "exam_hits": 0,
                "teacher_cues": [],
                "question_types": [],
                "evidence": [],
                "exam_evidence": [],
                "review_action": "",
            }
            topics.append(topic)
            topic_index[key] = topic

        topic["importance"] = normalize_importance(update.get("importance"), topic.get("importance", "C"))
        topic["score"] = int(topic.get("score") or 0) + clamp_int(update.get("score_delta"), -10, 20)
        for field in ("reason", "teacher_hint", "exam_hint"):
            value = str(update.get(field) or "").strip()
            if value:
                topic[f"llm_{field}"] = value[:500]
        action = str(update.get("review_action") or "").strip()
        if action:
            topic["review_action"] = action[:300]

    topics.sort(key=lambda item: {"A": 0, "B": 1, "C": 2}.get(item.get("importance", "C"), 2))
    analysis["llm"] = {
        "enabled": True,
        "status": "ok",
        "model": config.model.strip(),
        "base_url": redact_base_url(config.base_url),
        "summary": str(payload.get("summary") or "").strip()[:800],
        "exam_hints": safe_string_list(payload.get("exam_hints"), 12, 240),
        "study_plan": safe_string_list(payload.get("study_plan"), 12, 240),
    }


def topic_key(value: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", value).lower()[:40]


def find_near_topic(topics: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    key = topic_key(name)
    for topic in topics:
        other = topic_key(topic.get("name", ""))
        if not other or not key:
            continue
        if key in other or other in key:
            return topic
    return None


def normalize_importance(value: Any, default: str = "C") -> str:
    text = str(value or default).upper()
    return text if text in {"A", "B", "C"} else default


def clamp_int(value: Any, lower: int, upper: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    return max(lower, min(upper, number))


def safe_string_list(value: Any, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:item_limit] for item in value[:limit] if str(item).strip()]


def redact_base_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value.strip())
    if not parsed.netloc:
        return value.strip()
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))
