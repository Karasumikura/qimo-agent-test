import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analyzer import analyze_materials, build_markdown_report


def main() -> None:
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
    assert analysis["topics"], "expected topics"
    assert analysis["topics"][0]["importance"] == "A", analysis["topics"][0]
    report = build_markdown_report(analysis)
    assert "期末重点报告" in report
    assert "极限定理" in report


if __name__ == "__main__":
    main()
