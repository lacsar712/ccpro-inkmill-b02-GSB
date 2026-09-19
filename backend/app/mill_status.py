"""研磨机状态机规则：单条更新与批量更新共用同一套校验。"""

from app.models.mill import MILL_STATUSES, Mill
from app.models.workshop import Workshop

# 合法跳转：idle→grinding、idle→wash、grinding→wash、grinding→idle、wash→idle
ALLOWED_TRANSITIONS = frozenset(
    {
        ("idle", "grinding"),
        ("idle", "wash"),
        ("grinding", "wash"),
        ("grinding", "idle"),
        ("wash", "idle"),
    }
)

STATUS_LABELS = {"grinding": "研磨", "idle": "待机", "wash": "清洗"}


def normalize_status(value) -> str | None:
    """写入前把 status 归一为 grinding / idle / wash；非法值返回 None。"""
    text = str(value if value is not None else "").strip().lower()
    return text if text in MILL_STATUSES else None


def validate_transition(current: str, target: str, mill_code: str) -> str | None:
    """校验单次状态跳转，非法时返回带 millCode 的中文错误，否则返回 None。

    状态未变化视为无跳转（允许），其余跳转必须在 ALLOWED_TRANSITIONS 内。
    """
    if current == target:
        return None
    if (current, target) in ALLOWED_TRANSITIONS:
        return None
    return (
        f"研磨机 {mill_code} 不允许从「{STATUS_LABELS.get(current, current)}」"
        f"切换为「{STATUS_LABELS.get(target, target)}」"
    )


def grinding_conflict_message(db, changes) -> str | None:
    """校验"同一车间同时最多一台 grinding"。

    changes: [(mill_id | None, mill_code, workshop_id, target_status), ...]
    按应用本次变更后的最终状态判定；只有本次会把某车间变为 grinding 数量
    超过一台时才返回中文冲突错误，否则返回 None。
    """
    by_workshop: dict[int, list] = {}
    for mill_id, mill_code, workshop_id, target_status in changes:
        by_workshop.setdefault(workshop_id, []).append((mill_id, mill_code, target_status))

    for workshop_id, items in by_workshop.items():
        incoming = [code for _, code, target in items if target == "grinding"]
        if not incoming:
            # 本次没有往该车间新增 grinding，不可能导致违反互斥
            continue
        ids = [mill_id for mill_id, _, _ in items if mill_id is not None]
        query = db.query(Mill).filter(
            Mill.workshop_id == workshop_id, Mill.status == "grinding"
        )
        if ids:
            query = query.filter(~Mill.id.in_(ids))
        others = query.all()
        if len(others) + len(incoming) > 1:
            workshop = db.get(Workshop, workshop_id)
            name = workshop.name if workshop else f"#{workshop_id}"
            codes = [m.mill_code for m in others] + incoming
            return f"车间「{name}」同时最多一台研磨机处于研磨状态（{'、'.join(codes)}）"
    return None
