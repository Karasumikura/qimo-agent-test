from __future__ import annotations

import json
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analyzer import analyze_materials, build_markdown_report
from app.llm import LlmConfig, enrich_analysis_with_llm


class MockHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        assert body["model"] == "mock-model"
        assert self.headers.get("authorization") == "Bearer test-key"
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "summary": "极限定理和适用条件需要优先复习。",
                                "topic_updates": [
                                    {
                                        "name": "极限定理",
                                        "importance": "A",
                                        "score_delta": 8,
                                        "reason": "课堂明确说期末常考，往年题也考证明过程。",
                                        "teacher_hint": "老师用常考和一定掌握提示。",
                                        "exam_hint": "可能考证明或适用条件判断。",
                                        "review_action": "先背条件，再复盘证明链条。",
                                    }
                                ],
                                "exam_hints": ["证明题和条件判断题概率高。"],
                                "study_plan": ["整理一页极限定理条件清单。"],
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        materials = [
            {
                "id": "lecture-1",
                "course": "测试课程",
                "kind": "transcript",
                "original_name": "第1讲.srt",
                "transcript": "[00:10:02] 这个极限定理非常重要，期末考试常考，大家一定要掌握证明过程。",
                "extracted_text": "",
            },
            {
                "id": "exam-1",
                "course": "测试课程",
                "kind": "past_exam",
                "original_name": "2024往年题.txt",
                "transcript": "",
                "extracted_text": "1. 简述极限定理的证明过程，并说明适用条件。",
            },
        ]
        analysis = analyze_materials(materials, "测试课程")
        enriched = enrich_analysis_with_llm(
            analysis,
            materials,
            LlmConfig(
                enabled=True,
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                api_key="test-key",
                model="mock-model",
            ),
        )
        assert enriched["llm"]["status"] == "ok"
        assert enriched["llm"]["model"] == "mock-model"
        assert any(topic.get("llm_reason") for topic in enriched["topics"])
        report = build_markdown_report(enriched)
        assert "LLM 语义分析" in report
        assert "证明题和条件判断题概率高" in report
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
