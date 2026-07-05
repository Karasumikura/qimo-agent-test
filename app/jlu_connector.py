from __future__ import annotations

from dataclasses import dataclass


JLU_COURSE_LIBRARY_URL = "https://ilearntec.jlu.edu.cn/courselibrary-web/index"


@dataclass
class CourseResource:
    title: str
    url: str
    resource_type: str
    source: str = "学在吉大"


class JluLearningConnector:
    """Authorized connector placeholder.

    This app only processes materials the user can lawfully access. A real
    connector should use the user's normal login/session and platform APIs,
    and should not bypass captcha, DRM, anti-download controls, or course
    copyright restrictions.
    """

    def list_public_entrypoints(self) -> list[CourseResource]:
        return [
            CourseResource(
                title="学在吉大课程库",
                url=JLU_COURSE_LIBRARY_URL,
                resource_type="course_library",
            )
        ]
