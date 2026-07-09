"""失败类型枚举 - 用于结构化失败原因，配合 Dashboard 失败 Top 统计"""
from enum import Enum


class FailureReason(str, Enum):
    JSON_PARSE_ERROR = "JSON_PARSE_ERROR"
    SCHEMA_VALIDATION_ERROR = "SCHEMA_VALIDATION_ERROR"
    SELLING_POINT_DRIFT = "SELLING_POINT_DRIFT"
    STORYBOARD_MISSING = "STORYBOARD_MISSING"
    CONTENT_TOO_LONG = "CONTENT_TOO_LONG"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    JUDGE_REJECTED = "JUDGE_REJECTED"
    WORKER_CRASH = "WORKER_CRASH"
    DUPLICATE_MESSAGE = "DUPLICATE_MESSAGE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"


# 每种失败类型对应的处理策略
REPAIR_STRATEGY = {
    FailureReason.JSON_PARSE_ERROR: "json_repair",
    FailureReason.SCHEMA_VALIDATION_ERROR: "schema_repair",
    FailureReason.SELLING_POINT_DRIFT: "regenerate_script",
    FailureReason.STORYBOARD_MISSING: "regenerate_storyboard",
    FailureReason.CONTENT_TOO_LONG: "compress_script",
    FailureReason.MODEL_TIMEOUT: "model_fallback",
    FailureReason.JUDGE_REJECTED: "judge_feedback_retry",
    FailureReason.WORKER_CRASH: "resume_from_db",
    FailureReason.DUPLICATE_MESSAGE: "idempotent_skip",
    FailureReason.MANUAL_REVIEW: "manual_handoff",
    FailureReason.UNKNOWN_ERROR: "dead_letter",
    FailureReason.INVALID_STATE_TRANSITION: "dead_letter",
}
