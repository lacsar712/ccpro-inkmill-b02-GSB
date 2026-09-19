from decimal import Decimal

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.mill_status import (
    grinding_conflict_message,
    normalize_status,
    validate_transition,
)
from app.models.mill import Mill
from app.models.workshop import Workshop
from app.serializers import mill_json
from app.utils import error

bp = Blueprint("mills", __name__, url_prefix="/api/mills")


def _status_or_default(body: dict) -> str | None:
    return normalize_status(body.get("status") or "idle")


def _validate(body: dict) -> str | None:
    workshop_id = int(body.get("workshopId") or 0)
    if workshop_id <= 0:
        return "请选择所属车间"

    mill_code = str(body.get("millCode", "")).strip()
    if not mill_code:
        return "研磨机编号不能为空"

    pigment_base = str(body.get("pigmentBase", "")).strip()
    if not pigment_base:
        return "色浆基料不能为空"

    if _status_or_default(body) is None:
        return "状态无效，应为 grinding / idle / wash"

    db = SessionLocal()
    try:
        if not db.get(Workshop, workshop_id):
            return "所属车间不存在"
    finally:
        db.close()

    return None


@bp.get("")
@jwt_required()
def list_mills():
    db = SessionLocal()
    try:
        rows = db.query(Mill).order_by(Mill.id.desc()).all()
        return jsonify([mill_json(r) for r in rows])
    finally:
        db.close()


@bp.post("")
@jwt_required()
def create_mill():
    body = request.get_json(silent=True) or {}
    err = _validate(body)
    if err:
        return error(err, 400)

    status = _status_or_default(body)
    db = SessionLocal()
    try:
        conflict = grinding_conflict_message(
            db,
            [(None, str(body["millCode"]).strip(), int(body["workshopId"]), status)],
        )
        if conflict:
            return error(conflict, 409)

        row = Mill(
            workshop_id=int(body["workshopId"]),
            mill_code=str(body["millCode"]).strip(),
            pigment_base=str(body["pigmentBase"]).strip(),
            bowl_liters=Decimal(str(body.get("bowlLiters", 0))),
            status=status,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return error("该车间下研磨机编号已存在", 400)
        db.refresh(row)
        return jsonify(mill_json(row)), 201
    finally:
        db.close()


@bp.put("/<int:item_id>")
@jwt_required()
def update_mill(item_id: int):
    body = request.get_json(silent=True) or {}
    err = _validate(body)
    if err:
        return error(err, 400)

    db = SessionLocal()
    try:
        row = db.get(Mill, item_id)
        if not row:
            return error("研磨机不存在", 404)

        target_status = _status_or_default(body)
        target_workshop = int(body["workshopId"])

        # 与批量更新共用同一套状态机规则
        err = validate_transition(row.status, target_status, row.mill_code)
        if err:
            return error(err, 409)
        conflict = grinding_conflict_message(
            db, [(row.id, row.mill_code, target_workshop, target_status)]
        )
        if conflict:
            return error(conflict, 409)

        row.workshop_id = target_workshop
        row.mill_code = str(body["millCode"]).strip()
        row.pigment_base = str(body["pigmentBase"]).strip()
        row.bowl_liters = Decimal(str(body.get("bowlLiters", 0)))
        row.status = target_status
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return error("该车间下研磨机编号已存在", 400)
        db.refresh(row)
        return jsonify(mill_json(row))
    finally:
        db.close()


@bp.post("/batch-status")
@jwt_required()
def batch_status():
    body = request.get_json(silent=True) or {}

    raw_ids = body.get("millIds")
    if not isinstance(raw_ids, list) or not raw_ids:
        return error("请选择要批量更新的研磨机", 400)
    try:
        mill_ids = list(dict.fromkeys(int(i) for i in raw_ids))
    except (TypeError, ValueError):
        return error("millIds 格式无效", 400)

    target = normalize_status(body.get("status"))
    if target is None:
        return error("状态无效，应为 grinding / idle / wash", 400)

    db = SessionLocal()
    try:
        rows = db.query(Mill).filter(Mill.id.in_(mill_ids)).all()
        found = {r.id for r in rows}
        missing = [i for i in mill_ids if i not in found]
        if missing:
            return error(f"研磨机不存在：{', '.join(map(str, missing))}", 404)

        # 先整体校验，任一失败则不写入（与单条更新同一套规则）
        for row in rows:
            err = validate_transition(row.status, target, row.mill_code)
            if err:
                return error(err, 409)

        conflict = grinding_conflict_message(
            db, [(r.id, r.mill_code, r.workshop_id, target) for r in rows]
        )
        if conflict:
            return error(conflict, 409)

        for row in rows:
            row.status = target
        db.commit()
        return jsonify({"updated": len(rows), "items": [mill_json(r) for r in rows]})
    finally:
        db.close()


@bp.delete("/<int:item_id>")
@jwt_required()
def delete_mill(item_id: int):
    db = SessionLocal()
    try:
        row = db.get(Mill, item_id)
        if not row:
            return error("研磨机不存在", 404)
        db.delete(row)
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()
