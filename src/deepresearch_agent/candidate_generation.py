from __future__ import annotations

import csv
import unicodedata
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

INDUSTRIES = (
    "电子元器件",
    "半导体",
    "汽车零部件",
    "机械设备",
    "工业自动化",
    "仪器仪表与传感器",
    "电气设备",
    "光伏、储能与新能源设备",
    "金属与基础材料",
    "化工与新材料",
    "橡胶与塑料制品",
    "纺织与工业用布",
    "医疗器械",
    "医药与原料药制造",
    "包装、纸制品与印刷材料",
)

PRIMARY_INDUSTRY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("汽车零部件", ("汽车制造业",)),
    ("仪器仪表与传感器", ("仪器仪表制造业",)),
    ("医药与原料药制造", ("医药制造业",)),
    (
        "电子元器件",
        ("计算机、通信和其他电子设备制造业",),
    ),
    (
        "电气设备",
        ("电气机械和器材制造业",),
    ),
    (
        "橡胶与塑料制品",
        ("橡胶和塑料制品业",),
    ),
    (
        "纺织与工业用布",
        ("纺织业", "纺织服装、服饰业", "化学纤维制造业"),
    ),
    (
        "包装、纸制品与印刷材料",
        ("造纸和纸制品业", "印刷和记录媒介复制业"),
    ),
    (
        "化工与新材料",
        ("化学原料和化学制品制造业", "石油、煤炭及其他燃料加工业"),
    ),
    (
        "金属与基础材料",
        (
            "黑色金属冶炼和压延加工业",
            "有色金属冶炼和压延加工业",
            "金属制品业",
            "非金属矿物制品业",
            "废弃资源综合利用业",
        ),
    ),
    (
        "机械设备",
        (
            "通用设备制造业",
            "专用设备制造业",
            "铁路、船舶、航空航天和其他运输设备制造业",
        ),
    ),
)

SPECIFIC_BUSINESS_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("半导体", ("半导体", "集成电路", "晶圆", "芯片", "封装测试", "刻蚀设备")),
    ("医疗器械", ("医疗器械", "医用设备", "体外诊断", "医学影像")),
    (
        "光伏、储能与新能源设备",
        ("光伏", "储能", "锂电", "风电设备", "新能源设备", "电池", "太阳能"),
    ),
    ("工业自动化", ("工业自动化", "工业机器人", "数控系统", "伺服系统", "变频器")),
    ("仪器仪表与传感器", ("传感器", "测量仪器", "分析仪器", "检测仪器")),
)

BUSINESS_DETAIL_INDUSTRIES = {
    "电子元器件",
    "机械设备",
    "仪器仪表与传感器",
    "电气设备",
    "金属与基础材料",
    "化工与新材料",
    "橡胶与塑料制品",
}


@dataclass(frozen=True)
class Candidate:
    supplier_name: str
    industry: str


def classify_candidate(record: dict) -> str | None:
    source_industry = str(record.get("INDUSTRYCSRC1") or "")
    primary_industry = next(
        (
            industry
            for industry, keywords in PRIMARY_INDUSTRY_KEYWORDS
            if any(keyword in source_industry for keyword in keywords)
        ),
        None,
    )
    if primary_industry is None:
        return None

    if primary_industry in BUSINESS_DETAIL_INDUSTRIES:
        main_business = str(record.get("MAIN_BUSINESS") or "")
        for industry, keywords in SPECIFIC_BUSINESS_KEYWORDS:
            if any(keyword in main_business for keyword in keywords):
                return industry
    return primary_industry


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
