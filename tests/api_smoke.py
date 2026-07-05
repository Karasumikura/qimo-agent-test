from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


BASE_URL = "http://127.0.0.1:8000"


def post_json(path: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers={"content-type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def expect_http_error(path: str, payload: dict, expected_status: int) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers={"content-type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=15)
    except urllib.error.HTTPError as exc:
        assert exc.code == expected_status, exc.code
        return
    raise AssertionError(f"expected HTTP {expected_status}")


def main() -> int:
    try:
        post_json(
            "/api/materials/text",
            {
                "course": "接口测试课程",
                "kind": "transcript",
                "title": "第1讲.txt",
                "text": "[00:10:02] 这个极限定理非常重要，期末考试常考，大家一定要掌握证明过程。\n"
                "[00:12:30] 这里的适用条件很容易考，注意不要漏掉。",
            },
        )
        post_json(
            "/api/materials/text",
            {
                "course": "接口测试课程",
                "kind": "past_exam",
                "title": "2024往年题.txt",
                "text": "1. 简述极限定理的证明过程，并说明适用条件。\n"
                "2. 计算题：根据给定条件判断极限定理是否适用。",
            },
        )
        result = post_json("/api/analyze", {"course": "接口测试课程"})
        local_result = post_json(
            "/api/analyze",
            {"course": "接口测试课程", "llm": {"enabled": False}},
        )
        transcript_import = post_json(
            "/api/imports/from-page",
            {
                "course": "接口测试课程",
                "title": "页面转写",
                "transcript_text": "老师说这个知识点是期末重点，考试可能会出简答题。",
            },
        )
        expect_http_error(
            "/api/imports/from-url",
            {
                "course": "接口测试课程",
                "title": "内网测试",
                "url": "http://127.0.0.1/private.mp4",
            },
            400,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"API smoke failed: {exc}", file=sys.stderr)
        return 1

    topics = result["analysis"]["topics"]
    assert topics, "expected topics"
    assert local_result["analysis"]["llm"]["status"] == "skipped"
    assert transcript_import["material"]["status"] in {"downloading", "ready"}
    assert result["analysis"]["course"] == "接口测试课程"
    assert "极限定理" in result["report"]
    print(result["report_url"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
