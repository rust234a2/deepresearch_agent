from __future__ import annotations

import csv
import unicodedata
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path


INDUSTRY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("半导体", ("半导体", "集成电路", "晶圆", "芯片", "封装测试", "刻蚀设备")),
    ("医疗器械", ("医疗器械", "医用设备", "体外诊断", "医学影像")),
    ("医药与原料药制造", ("医药制造", "原料药", "生物制药", "中药", "药物制剂")),
    ("仪器仪表与传感器", ("仪器仪表", "传感器", "测量仪器", "分析仪器", "检测仪器")),
    ("汽车零部件", ("汽车零部件", "汽车配件", "汽车制造", "车用零部件")),
    ("工业自动化", ("工业自动化", "工业机器人", "数控系统", "伺服系统", "变频器")),
    (
        "电子元器件",
        (
            "计算机、通信和其他电子设备制造",
            "电子元件",
            "电子器件",
            "元器件",
            "印制电路",
            "光电子",
        ),
    ),
    (
        "电气设备",
        ("电气机械和器材制造", "输配电", "变压器", "电线电缆", "开关设备", "电机制造"),
    ),
    (
        "光伏、储能与新能源设备",
        ("光伏", "储能", "锂电", "风电设备", "新能源设备", "电池制造", "太阳能设备"),
    ),
    (
        "橡胶与塑料制品",
        ("橡胶和塑料制品", "橡胶制品", "塑料制品", "改性塑料"),
    ),
    (
        "纺织与工业用布",
        ("纺织", "工业用布", "服装制造", "化学纤维制造", "非织造布"),
    ),
    (
        "包装、纸制品与印刷材料",
        ("造纸和纸制品", "印刷和记录媒介复制", "包装材料", "包装制品"),
    ),
    (
        "化工与新材料",
        ("化学原料和化学制品制造", "化工", "新材料", "涂料", "农药", "复合材料"),
    ),
    (
        "金属与基础材料",
        ("黑色金属冶炼", "有色金属冶炼", "金属制品", "钢铁", "铜材", "铝材", "稀土"),
    ),
    (
        "机械设备",
        (
            "通用设备制造",
            "专用设备制造",
            "机械设备",
            "工程机械",
            "轨道交通设备",
            "船舶制造",
            "航空航天器制造",
            "泵及真空设备",
            "阀门制造",
        ),
    ),
)

INDUSTRIES = tuple(industry for industry, _ in INDUSTRY_KEYWORDS)


@dataclass(frozen=True)
class Candidate:
    supplier_name: str
    industry: str


def classify_candidate(record: dict) -> str | None:
    text = " ".join(
        str(record.get(key) or "")
        for key in ("INDUSTRYCSRC1", "MAIN_BUSINESS", "BUSINESS_SCOPE")
    )
    for industry, keywords in INDUSTRY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return industry
    return None


def build_candidates(records: Iterable[dict], limit: int = 5000) -> list[Candidate]:
    unique: dict[str, Candidate] = {}
    for record in records:
        name = " ".join(str(record.get("ORG_NAME") or "").split())
        industry = classify_candidate(record)
        if not name or industry is None:
            continue
        normalized_name = unicodedata.normalize("NFKC", name).casefold()
        unique.setdefault(normalized_name, Candidate(name, industry))
    return select_balanced_candidates(list(unique.values()), limit)


def select_balanced_candidates(candidates: Iterable[Candidate], limit: int) -> list[Candidate]:
    if limit < 1:
        return []

    grouped: dict[str, deque[Candidate]] = defaultdict(deque)
    for candidate in sorted(candidates, key=lambda item: (item.industry, item.supplier_name)):
        grouped[candidate.industry].append(candidate)

    selected: list[Candidate] = []
    active_industries = [industry for industry in INDUSTRIES if grouped[industry]]
    while active_industries and len(selected) < limit:
        next_round: list[str] = []
        for industry in active_industries:
            if len(selected) >= limit:
                break
            selected.append(grouped[industry].popleft())
            if grouped[industry]:
                next_round.append(industry)
        active_industries = next_round
    return selected


def write_candidates_csv(candidates: Iterable[Candidate], output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["supplier_name", "industry"])
        writer.writeheader()
        writer.writerows(asdict(candidate) for candidate in candidates)


def parse_source_page(payload: dict) -> tuple[list[dict], int]:
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("Source response does not contain a result object")

    pages = int(result.get("pages") or 0)
    records: list[dict] = []
    for item in result.get("data") or []:
        country = str(item.get("COUNTRY") or "")
        security_code = str(item.get("SECUCODE") or "")
        is_mainland_company = "中国" in country or "china" in country.casefold()
        is_mainland_listing = security_code.endswith((".SH", ".SZ", ".BJ"))
        if (
            str(item.get("LISTING_STATE")) == "0"
            and is_mainland_company
            and is_mainland_listing
            and str(item.get("ORG_NAME") or "").strip()
        ):
            records.append(item)
    return records, pages
