from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any


CUE_WEIGHTS: dict[str, int] = {
    "必考": 8,
    "一定会考": 8,
    "会考": 7,
    "考试": 5,
    "期末": 5,
    "重点": 6,
    "很重要": 6,
    "重要": 4,
    "掌握": 4,
    "必须": 4,
    "一定": 4,
    "注意": 3,
    "记住": 4,
    "常考": 7,
    "容易考": 6,
    "可能考": 5,
    "题型": 4,
    "简答": 5,
    "计算": 4,
    "证明": 4,
    "例题": 3,
    "作业": 3,
    "易错": 5,
    "难点": 5,
    "关键": 4,
    "反复": 3,
}

QUESTION_CUES = {
    "选择",
    "填空",
    "判断",
    "简答",
    "论述",
    "计算",
    "证明",
    "分析",
    "解释",
    "名词解释",
}

STOP_FRAGMENTS = {
    "这个",
    "这里",
    "我们",
    "大家",
    "同学们",
    "一定",
    "需要",
    "必须",
    "注意",
    "重点",
    "考试",
    "期末",
    "就是",
    "问题",
    "时候",
    "内容",
    "知识点",
    "老师",
}


def sentence_split(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?；;])\s+|(?<=[。！？!?；;])", text)
    result: list[str] = []
    for part in parts:
        cleaned = part.strip()
        if not cleaned:
            continue
        if len(cleaned) <= 180:
            result.append(cleaned)
            continue
        result.extend(chunk.strip() for chunk in re.split(r"[，,]", cleaned) if chunk.strip())
    return result


def parse_timestamped_segments(text: str, material: dict[str, Any]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    timestamp: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        content = " ".join(buffer).strip()
        buffer = []
        for sentence in sentence_split(content):
            segments.append(
                {
                    "text": sentence,
                    "timestamp": timestamp,
                    "material_id": material["id"],
                    "material_name": material["original_name"],
                    "kind": material["kind"],
                }
            )

    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if re.fullmatch(r"\d+", line):
            continue
        if "-->" in line:
            flush()
            timestamp = normalize_time(line.split("-->", 1)[0].strip())
            continue
        match = re.match(r"^\[?(\d{1,2}:\d{2}(?::\d{2})?(?:[,.]\d{1,3})?)\]?\s+(.+)$", line)
        if match:
            flush()
            timestamp = normalize_time(match.group(1))
            buffer.append(match.group(2))
            continue
        buffer.append(line)
    flush()
    return segments


def normalize_time(value: str) -> str:
    value = value.replace(",", ".")
    pieces = value.split(".")[0].split(":")
    if len(pieces) == 2:
        return f"00:{pieces[0].zfill(2)}:{pieces[1].zfill(2)}"
    if len(pieces) == 3:
        return f"{pieces[0].zfill(2)}:{pieces[1].zfill(2)}:{pieces[2].zfill(2)}"
    return value


def cue_hits(text: str) -> list[str]:
    return [cue for cue in CUE_WEIGHTS if cue in text]


def clean_topic(value: str) -> str:
    value = re.sub(r"^[：:，,、\s]+", "", value)
    value = re.sub(r"[。！？；;，,：:\s]+$", "", value)
    value = re.sub(r"^(这个|这里|本节|本章|这一块|这部分|主要|关于|对于)", "", value)
    value = re.sub(r"(一定|必须|需要|重点|考试|期末|掌握|理解|注意|记住)+", "", value)
    value = value.strip(" ：:，,、")
    if len(value) > 28:
        value = value[:28].rstrip("，,、")
    return value or "未命名知识点"


def extract_topic(sentence: str) -> str:
    patterns = [
        r"(?:重点|掌握|理解|熟悉|注意|记住|常考|会考|必考|容易考|可能考)[的是为：:，,\s]*([^。！？；;]{2,32})",
        r"([^。！？；;，,]{2,32})(?:是|属于|叫做|称为|的定义|的性质|的推导|的证明|的计算|会考|常考|必考|很重要|比较重要|重点|易错|难点)",
        r"(第[一二三四五六七八九十百0-9]+[章节讲][^。！？；;，,]{0,24})",
        r"(?:公式|定理|定义|概念|方法|模型|算法|原理)[：:，,\s]*([^。！？；;]{2,32})",
    ]
    for pattern in patterns:
        match = re.search(pattern, sentence)
        if match:
            return clean_topic(match.group(1))

    compact = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9（）()、·\-]", " ", sentence)
    pieces = [piece for piece in re.split(r"\s+", compact) if piece and piece not in STOP_FRAGMENTS]
    if not pieces:
        return clean_topic(sentence)
    return clean_topic(max(pieces, key=len))


def topic_key(topic: str) -> str:
    normalized = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", topic).lower()
    for fragment in STOP_FRAGMENTS:
        normalized = normalized.replace(fragment, "")
    return normalized[:32] or topic.lower()


def split_exam_questions(text: str) -> list[str]:
    text = re.sub(r"\r\n", "\n", text)
    chunks = re.split(
        r"(?m)(?=^\s*(?:\d+[\.\、．]|[一二三四五六七八九十]+[、.．]|[（(]\d+[）)]|第\s*\d+\s*题))",
        text,
    )
    questions = []
    for chunk in chunks:
        cleaned = re.sub(r"\s+", " ", chunk).strip()
        if len(cleaned) >= 8:
            questions.append(cleaned[:500])
    if questions:
        return questions
    return [sentence for sentence in sentence_split(text) if len(sentence) >= 8]


def extract_exam_topic(question: str) -> str:
    cleaned = re.sub(r"^\s*(?:\d+[\.\、．]|[一二三四五六七八九十]+[、.．]|[（(]\d+[）)]|第\s*\d+\s*题)", "", question)
    cleaned = re.sub(r"(请|试|简述|论述|计算|证明|分析|解释|说明|选择|填空|判断|求|写出|给出)", "", cleaned)
    return extract_topic(cleaned)


def overlap_score(topic: str, question: str) -> float:
    key = topic_key(topic)
    if key and key in topic_key(question):
        return 1.0
    topic_chars = {char for char in key if "\u4e00" <= char <= "\u9fff"}
    question_chars = {char for char in topic_key(question) if "\u4e00" <= char <= "\u9fff"}
    if not topic_chars:
        return 0.0
    return len(topic_chars & question_chars) / len(topic_chars)


def make_bucket(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "score": 0,
        "teacher_mentions": 0,
        "teacher_cues": Counter(),
        "exam_hits": 0,
        "question_types": Counter(),
        "evidence": [],
        "exam_evidence": [],
    }


def add_evidence(bucket: dict[str, Any], segment: dict[str, Any], cues: list[str], weight: int) -> None:
    bucket["score"] += weight
    bucket["teacher_mentions"] += 1
    bucket["teacher_cues"].update(cues)
    if len(bucket["evidence"]) < 6:
        bucket["evidence"].append(
            {
                "source": segment["material_name"],
                "timestamp": segment.get("timestamp"),
                "text": segment["text"][:220],
                "cues": cues,
            }
        )


def question_type(question: str) -> str:
    for cue in QUESTION_CUES:
        if cue in question:
            return cue
    return "综合"


def analyze_materials(materials: list[dict[str, Any]], course: str = "") -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = {}
    source_counts = Counter()
    lecture_segments: list[dict[str, Any]] = []
    exam_questions: list[dict[str, Any]] = []

    for material in materials:
        source_counts[material["kind"]] += 1
        text = (material.get("transcript") or material.get("extracted_text") or "").strip()
        if not text:
            continue
        if material["kind"] == "past_exam":
            for question in split_exam_questions(text):
                exam_questions.append(
                    {
                        "text": question,
                        "source": material["original_name"],
                        "type": question_type(question),
                    }
                )
        else:
            lecture_segments.extend(parse_timestamped_segments(text, material))

    for segment in lecture_segments:
        cues = cue_hits(segment["text"])
        if not cues:
            continue
        topic = extract_topic(segment["text"])
        key = topic_key(topic)
        bucket = buckets.setdefault(key, make_bucket(topic))
        add_evidence(bucket, segment, cues, sum(CUE_WEIGHTS[cue] for cue in cues))

    for question in exam_questions:
        matched_key = None
        best_score = 0.0
        for key, bucket in buckets.items():
            score = overlap_score(bucket["name"], question["text"])
            if score > best_score:
                matched_key = key
                best_score = score
        if matched_key is None or best_score < 0.38:
            topic = extract_exam_topic(question["text"])
            matched_key = topic_key(topic)
            buckets.setdefault(matched_key, make_bucket(topic))

        bucket = buckets[matched_key]
        bucket["exam_hits"] += 1
        bucket["score"] += 5
        bucket["question_types"].update([question["type"]])
        if len(bucket["exam_evidence"]) < 5:
            bucket["exam_evidence"].append(
                {
                    "source": question["source"],
                    "type": question["type"],
                    "text": question["text"][:240],
                }
            )

    topics = []
    for bucket in buckets.values():
        score = int(bucket["score"])
        if score >= 18 or bucket["exam_hits"] >= 4:
            importance = "A"
        elif score >= 10 or bucket["exam_hits"] >= 2:
            importance = "B"
        else:
            importance = "C"
        topics.append(
            {
                "name": bucket["name"],
                "importance": importance,
                "score": score,
                "teacher_mentions": bucket["teacher_mentions"],
                "exam_hits": bucket["exam_hits"],
                "teacher_cues": [
                    {"cue": cue, "count": count}
                    for cue, count in bucket["teacher_cues"].most_common()
                ],
                "question_types": [
                    {"type": cue, "count": count}
                    for cue, count in bucket["question_types"].most_common()
                ],
                "evidence": bucket["evidence"],
                "exam_evidence": bucket["exam_evidence"],
                "review_action": review_action(importance, bucket["exam_hits"], bucket["teacher_mentions"]),
            }
        )

    topics.sort(key=lambda item: (item["importance"], -item["score"]))
    topics.sort(key=lambda item: {"A": 0, "B": 1, "C": 2}[item["importance"]])

    return {
        "course": course,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_counts": dict(source_counts),
        "material_count": len(materials),
        "lecture_segment_count": len(lecture_segments),
        "exam_question_count": len(exam_questions),
        "topics": topics,
        "warnings": build_warnings(materials, lecture_segments, exam_questions),
    }


def build_warnings(
    materials: list[dict[str, Any]],
    lecture_segments: list[dict[str, Any]],
    exam_questions: list[dict[str, Any]],
) -> list[str]:
    warnings: list[str] = []
    if not lecture_segments:
        warnings.append("未检测到可分析的课堂文字稿。")
    if not exam_questions:
        warnings.append("未检测到往年题文本，重要度主要来自课堂提示。")
    pending = [item["original_name"] for item in materials if not (item.get("transcript") or item.get("extracted_text"))]
    if pending:
        warnings.append(f"{len(pending)} 个文件缺少可分析文本，需要转写、OCR 或手动粘贴文字。")
    return warnings


def review_action(importance: str, exam_hits: int, teacher_mentions: int) -> str:
    if importance == "A" and exam_hits and teacher_mentions:
        return "优先复习：整理定义、推导、典型题和易错条件。"
    if importance == "A":
        return "优先复习：补齐课堂证据或往年题证据后做专题训练。"
    if importance == "B":
        return "第二轮复习：掌握核心概念，至少做一组对应题。"
    return "浏览复习：确认概念边界，避免基础失分。"


def build_markdown_report(analysis: dict[str, Any]) -> str:
    course = analysis.get("course") or "未命名课程"
    lines = [
        f"# {course} 期末重点报告",
        "",
        f"- 生成时间：{analysis['generated_at']}",
        f"- 分析资料：{analysis['material_count']} 份",
        f"- 课堂片段：{analysis['lecture_segment_count']} 条",
        f"- 往年题：{analysis['exam_question_count']} 条",
        "",
        "> 说明：本报告是基于课堂文字、老师提示词和往年题匹配的复习推断，不等同于老师承诺的考试范围。",
        "",
    ]

    if analysis.get("warnings"):
        lines.append("## 注意")
        for warning in analysis["warnings"]:
            lines.append(f"- {warning}")
        lines.append("")

    llm = analysis.get("llm") or {}
    if llm.get("enabled"):
        lines.append("## LLM 语义分析")
        if llm.get("status") == "ok":
            lines.append(f"- 模型：{llm.get('model', '')}")
            if llm.get("summary"):
                lines.append(f"- 总评：{llm['summary']}")
            if llm.get("exam_hints"):
                lines.append("- 考题暗示：")
                for hint in llm["exam_hints"]:
                    lines.append(f"  - {hint}")
            if llm.get("study_plan"):
                lines.append("- 复习计划：")
                for action in llm["study_plan"]:
                    lines.append(f"  - {action}")
        else:
            lines.append(f"- 状态：失败")
            if llm.get("error"):
                lines.append(f"- 错误：{llm['error']}")
        lines.append("")

    for level in ("A", "B", "C"):
        topics = [topic for topic in analysis["topics"] if topic["importance"] == level]
        if not topics:
            continue
        title = {"A": "优先级 A", "B": "优先级 B", "C": "优先级 C"}[level]
        lines.append(f"## {title}")
        for index, topic in enumerate(topics, start=1):
            lines.extend(
                [
                    "",
                    f"### {index}. {topic['name']}",
                    f"- 评分：{topic['score']}",
                    f"- 老师提示：{topic['teacher_mentions']} 次",
                    f"- 往年题命中：{topic['exam_hits']} 次",
                    f"- 复习动作：{topic['review_action']}",
                ]
            )
            if topic["teacher_cues"]:
                cues = "、".join(f"{item['cue']} x{item['count']}" for item in topic["teacher_cues"][:6])
                lines.append(f"- 提示词：{cues}")
            if topic["question_types"]:
                types = "、".join(f"{item['type']} x{item['count']}" for item in topic["question_types"][:6])
                lines.append(f"- 题型：{types}")
            if topic.get("llm_reason"):
                lines.append(f"- AI 判断：{topic['llm_reason']}")
            if topic.get("llm_teacher_hint"):
                lines.append(f"- 老师暗示：{topic['llm_teacher_hint']}")
            if topic.get("llm_exam_hint"):
                lines.append(f"- 命题方向：{topic['llm_exam_hint']}")
            if topic["evidence"]:
                lines.append("- 课堂证据：")
                for evidence in topic["evidence"][:3]:
                    stamp = f" {evidence['timestamp']}" if evidence.get("timestamp") else ""
                    lines.append(f"  - {evidence['source']}{stamp}：{evidence['text']}")
            if topic["exam_evidence"]:
                lines.append("- 往年题证据：")
                for evidence in topic["exam_evidence"][:3]:
                    lines.append(f"  - {evidence['source']} [{evidence['type']}]：{evidence['text']}")
        lines.append("")

    if not analysis["topics"]:
        lines.extend(
            [
                "## 暂无结论",
                "",
                "当前资料没有提取到足够的重点线索。建议上传课堂文字稿、字幕文件或往年题文本后重新分析。",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"
