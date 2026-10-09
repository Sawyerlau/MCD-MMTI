"""
麦麦人格 MMTI - 人格判定引擎（可运行 Demo）

MCD-MMTI（McDonald's Mood & Taste Index）
读订单、读券、读积分，算出你此刻是哪个人格。

本文件是 MMTI 人格判定核心逻辑的可运行参考实现，用于演示：
  1. 16 型人格坐标系的数据结构
  2. 券时段轮转判定机制
  3. 三段式人格卡的输出格式

数据来源说明：
  真实运行环境下，以上数据由麦当劳 MCP Server 提供（见 MCP_INTEGRATION.md）。
  本 Demo 内置的样例数据采集自 MCP 实测返回，仅用于离线演示判定逻辑。
  所有餐品营养信息、价格与活动均以麦当劳官方实时数据为准。

合规声明（见 CONTEST_DECLARATION.md）：
  本项目输出仅作为餐品选择参考，不构成医疗或营养诊断。
  热量与钠含量均为「信息参考」，不构成健康建议。

运行：
  python main.py --now 2026-10-09 21:05
  python main.py --list
"""

from __future__ import annotations

import argparse
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# ============================================================================
# 一、16 型人格坐标系
# ============================================================================

FAMILY_APPETITE = "食欲型"
FAMILY_BRAIN = "脑子型"
FAMILY_BODY = "身体型"
FAMILY_MOOD = "心情型"

FAMILY_TAGLINE = {
    FAMILY_APPETITE: "大口吃才爽",
    FAMILY_BRAIN: "会算才吃",
    FAMILY_BODY: "吃得干净",
    FAMILY_MOOD: "吃得开心",
}


@dataclass(frozen=True)
class Persona:
    """一张人格卡的静态定义。谐音来源与人设均为产品文案。"""

    key: str
    name: str
    family: str
    homophone_from: str  # 谐音来源的麦劳产品
    tagline: str  # 一句话人设
    anchor: str  # 推荐锚点描述
    # 该人格下推荐餐品的热量参考区间（kcal），仅用于信息展示
    kcal_range: tuple[int, int] = (0, 0)


PERSONAS: tuple[Persona, ...] = (
    # ---------------- 食欲型 · 大口吃才爽 ----------------
    Persona("king", "卷王", FAMILY_APPETITE, "巨无霸「大」",
            "胃口就是实力", "高热量单品，不设热量上限", (400, 550)),
    Persona("biggest", "干饭最强音", FAMILY_APPETITE, "那么大鸡排「那么大」",
            "要么不点，要点最大份", "大份鸡排、盒饭类主食", (350, 450)),
    Persona("double", "绝代双爽", FAMILY_APPETITE, "绝代双翅「翅」→爽",
            "一口封神，艳压群芳", "鸡翅、双拼小食", (400, 550)),
    Persona("starving", "急死汉堡包", FAMILY_APPETITE, "吉士汉堡包「吉士」→急死",
            "三点半就饿了", "吉士汉堡、能量补给型", (250, 350)),
    # ---------------- 脑子型 · 会算才吃 ----------------
    Persona("coupon", "券时钟", FAMILY_BRAIN, "券的有效期",
            "绝不浪费一张券", "优先匹配当前时段有效券"),
    Persona("points", "积分守财奴", FAMILY_BRAIN, "麦金卡「金」",
            "攒够就换霸王餐", "积分抽奖、积分兑换"),
    Persona("random", "随性真香派", FAMILY_BRAIN, "精选超值随心配",
            "闭眼点，13.9 真香", "高复购商品、随机应变"),
    Persona("perfect", "满分解", FAMILY_BRAIN, "麦满分「满分」",
            "一顿饭也要满分", "麦满分系列、套餐全齐"),
    # ---------------- 身体型 · 吃得干净 ----------------
    Persona("plank", "平板支撑", FAMILY_BODY, "苹板支撑 Pro",
            "汉堡名叫平板支撑", "均衡型，控制热量但保证蛋白", (400, 550)),
    Persona("oat", "燕麦轻盈派", FAMILY_BODY, "冰燕麦奶铁",
            "轻盈的一餐", "低卡饮品、燕麦系", (50, 250)),
    Persona("zero", "零糖战士", FAMILY_BODY, "无糖可口可乐",
            "快乐不必加糖", "0 kcal 饮品、无糖选项", (0, 150)),
    Persona("protein", "蛋白底线", FAMILY_BODY, "纯牛奶（盒装）",
            "别的都能省，蛋白不能", "高蛋白单品、补钙饮品", (100, 350)),
    # ---------------- 心情型 · 吃得开心 ----------------
    Persona("midnight", "深夜被鼓励", FAMILY_MOOD, "热朱古力「中鼓励」",
            "深夜给胃一个拥抱", "夜宵时段、热饮甜品", (100, 300)),
    Persona("kid", "童心不老", FAMILY_MOOD, "麦麦趣鸡球「去秋游」",
            "六十岁也想吃儿童餐", "儿童餐、小份甜品", (200, 350)),
    Persona("pie", "派系气氛组", FAMILY_MOOD, "香芋派「派」",
            "有派才有气氛", "派类、分享装", (200, 300)),
    Persona("slacker", "摸鱼达人", FAMILY_MOOD, "酥酥多笋卷「多损」",
            "上班的一点点慰藉", "卷类、小食", (250, 400)),
)

PERSONA_MAP: dict[str, Persona] = {p.key: p for p in PERSONAS}


# ============================================================================
# 二、MCP 真实返回的数据结构（采样自实测，字段与线上一致）
# ============================================================================


@dataclass
class Coupon:
    """对应 query-my-coupons 返回条目。"""

    title: str
    price_cny: float
    start: datetime
    end: datetime
    weekdays: tuple[int, ...]  # 0=周一 ... 6=周日，与 datetime.weekday() 对齐
    start_hour: int
    end_hour: int
    dine_in_only: bool = False

    def active_at(self, when: datetime) -> bool:
        """判断该券在指定时刻是否有效。MMTI 时段轮转的核心判据。"""
        if when.weekday() not in self.weekdays:
            return False
        if not (self.start <= when <= self.end):
            return False
        hour = when.hour + when.minute / 60
        return self.start_hour <= hour < self.end_hour

    def expires_today(self, when: datetime) -> bool:
        return self.end.date() == when.date()


@dataclass
class OrderItem:
    """对应 order-list 中 orderProductList[].comboItemList[] 的子项。"""

    name: str
    code: str
    quantity: int = 1


@dataclass
class Order:
    """对应 order-list 返回条目。

    combo_items 与 nutrition 由 MMTI 在本地关联匹配（MCP 分两个接口返回），
    分别来自 order-list 的 comboItemList 与 list-nutrition-foods。
    """

    order_id: str
    created_at: datetime
    product_name: str
    product_code: str
    amount_cny: float
    store_name: str
    combo_items: list[OrderItem] = field(default_factory=list)
    nutrition: Optional["NutritionItem"] = None
    # 子项部分匹配时的结果，仅作品类参考，不参与热量统计（见 build_taste_profile）
    partial_nutrition: Optional["NutritionItem"] = None

    @property
    def all_item_names(self) -> list[str]:
        """本单所有餐品名称，含套餐子项。"""
        names = [self.product_name]
        names += [i.name for i in self.combo_items]
        return names

    @property
    def hour(self) -> int:
        return self.created_at.hour

    @property
    def is_work_hour(self) -> bool:
        """工作日 10:00-17:00 —— 摸鱼达人判定用的时间窗。"""
        return self.created_at.weekday() < 5 and 10 <= self.hour < 17


@dataclass
class PointAccount:
    """对应 query-my-account 返回 data 字段。"""

    available: float
    accumulated: float
    used: float
    expired: float
    currency: str = "麦享会积分"


@dataclass
class Lottery:
    """对应 query-lottery-info 返回要点。"""

    draw_point: float
    best_prize: str


@dataclass
class NutritionItem:
    """对应 list-nutrition-foods 返回行。"""

    name: str
    kcal: int
    protein: float
    fat: float
    sodium: int


@dataclass
class MMTIContext:
    """一次 MMTI 判定所需的全部输入。"""

    now: datetime
    coupons: list[Coupon] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)
    points: Optional[PointAccount] = None
    lottery: Optional[Lottery] = None
    nutrition: list[NutritionItem] = field(default_factory=list)


# ============================================================================
# 三、人格判定引擎
# ============================================================================


@dataclass
class PersonaVerdict:
    """一次判定的完整结果：人格 + 归因 + 支撑数据。"""

    persona: Persona
    reason: str  # 归因话术，必须包含真实数据
    facts: list[str] = field(default_factory=list)  # 分享卡第二段
    confidence: str = "中"  # 高/中/低

    @property
    def family_tagline(self) -> str:
        return f"{self.persona.family} · {FAMILY_TAGLINE[self.persona.family]}"


def _parse_weekdays(spec: str) -> tuple[int, ...]:
    """把「周一、二、三、四、五」解析为 (0,1,2,3,4)。"""
    table = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6}
    return tuple(table[ch] for ch in spec if ch in table)


# ============================================================================
# 三、口味特征分析
#
# 历史订单（order-list）与营养库（list-nutrition-foods）分属两个 MCP 接口，
# 这里在本地关联：订单餐品名 → 营养条目，得到可计算的行为特征。
# ============================================================================

# 品类关键词表。命中即归入该品类，用于计算占比。
# 顺序即匹配优先级：特异性高的放前面。
# 例如「儿童鱼排堡」必须先于「鱼排」命中，否则会被误判成鱼类。
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "kids": ("儿童", "开心乐园", "小 Mega", "小士"),
    "roll": ("营养卷", "笋卷", "卷"),
    "pie": ("派",),
    "chicken": ("鸡腿堡", "鸡翅", "鸡块", "麦乐鸡", "脆汁鸡", "鸡排",
                "炸鸡", "辣翅", "趣鸡球", "V翅"),
    "fish": ("鱼排", "鳕鱼", "麦香鱼", "鱼堡"),
    "burger": ("汉堡", "巨无霸", "吉士", "堡"),
    "drink": ("可乐", "雪碧", "红茶", "奶茶", "奶铁", "美式", "拿铁", "卡布",
              "豆浆", "牛奶", "果汁", "咖啡", "水"),
    "dessert": ("旋", "新地", "筒", "布丁", "松饼"),
}

# 特征阈值（占比，超过即判定该品类人格）
THRESHOLD_MAJORITY = 0.40  # 绝对多数
THRESHOLD_SEGMENT = 0.25   # 显著份额

# 摸鱼达人判定：工作日 10:00-17:00 下单占比
THRESHOLD_WORK_HOUR = 0.30


@dataclass
class TasteProfile:
    """从历史订单与营养库关联出的行为特征。"""

    total_orders: int = 0
    category_ratio: dict[str, float] = field(default_factory=dict)
    avg_kcal: Optional[float] = None
    avg_protein: Optional[float] = None
    avg_sodium: Optional[float] = None
    high_kcal_ratio: float = 0.0  # 单品 500 kcal 以上的订单占比
    zero_drink_ratio: float = 0.0  # 点了0/极低卡饮品的订单占比
    work_hour_ratio: float = 0.0  # 工作日 10-17 点下单占比
    matched_orders: int = 0  # 成功关联营养数据的订单数


def _norm(name: str) -> str:
    """餐品名归一化，用于营养库与品类模糊匹配。

    MCP 返回的餐品名带大量营销修饰与规格后缀，而营养库用的是标准品名。
    例：「那么大鸡排（椒盐风味）」→「那么大鸡排」
        「可乐麦炫酷」→ 去营销词后按子串命中「可口可乐」

    注意：杯型（大杯/中杯/小杯）必须保留，否则 0 卡与大杯会被混为一谈。
    """
    s = name.strip()
    # 去括号内容（椒盐风味、限量装等）
    for l, r in (("（", "）"), ("(", ")"), ("【", "】"), ("[", "]")):
        if l in s and r in s:
            s = s[:s.index(l)] + s[s.index(r) + 1:]
    # 去营销后缀词，但保留规格
    for noise in ("麦炫酷", "会员专享", "经典款", "升级款", "超值"):
        s = s.replace(noise, "")
    return s.strip()


def _match_nutrition(name: str, index: dict[str, NutritionItem]) -> Optional[NutritionItem]:
    """在营养库中匹配餐品，依次尝试精确、归一化精确、子串包含三级策略。

    匹配优先级必须保证杯型优先：
    「无糖可口可乐中杯」应命中中杯（0 kcal），而非被「无糖可口可乐大杯」抢占。
    """
    if name in index:
        return index[name]
    n = _norm(name)
    if n in index:
        return index[n]
    # 子串包含：取最长命中，避免短词抢占长词
    hits = [k for k in index if k and k in n]
    return index[max(hits, key=len)] if hits else None


def _category_of(name: str) -> Optional[str]:
    """判定单个餐品所属品类。返回 None 表示不属于任何已定义品类。

    品类关键词必须按特异性排序——「儿童鱼排堡」要先于「鱼排」命中，
    否则儿童餐会被误判为鱼类（实测踩坑）。
    """
    n = _norm(name)
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(k in n for k in kws):
            return cat
    return None


def build_taste_profile(ctx: MMTIContext) -> TasteProfile:
    """构建口味特征。所有比例均基于真实订单计算，不做推断。

    关键处理：套餐类订单（主品为「超值随心配」这类套餐名）在营养库中
    没有对应条目，必须按子项**累加**营养值，不能取第一个匹配项。
    （实测踩坑：曾把 147 kcal 的饮料当成整单热量，导致人格误判为「燕麦轻盈派」）
    """
    prof = TasteProfile(total_orders=len(ctx.orders))
    if not ctx.orders:
        return prof

    index = {n.name: n for n in ctx.nutrition}
    matched: list[tuple[Order, NutritionItem]] = []
    cat_hits: dict[str, int] = {k: 0 for k in CATEGORY_KEYWORDS}

    for o in ctx.orders:
        names = o.all_item_names

        # ---- 营养关联：主品优先，否则按子项累加 ----
        main_hit = index.get(o.product_name) or _match_nutrition(o.product_name, index)
        if main_hit is not None:
            o.nutrition = main_hit
        else:
            # 套餐：累加所有能匹配上的子项
            parts = [p for p in (_match_nutrition(i.name, index) for i in o.combo_items)
                     if p is not None]
            total_subs = len(o.combo_items)
            # 关键：子项匹配不全时不能当作完整热量用。
            # 例：子项「高达吉士双牛堡」不在营养库，只匹配到 0 卡可乐，
            # 若直接取用会把一单算成 0 kcal（实测踩坑）。
            # 规则：覆盖率不足 60% 时视为匹配失败，交由上层按缺失处理。
            coverage = len(parts) / total_subs if total_subs else 0.0
            if parts and coverage >= 0.6:
                o.nutrition = NutritionItem(
                    name=f"{o.product_name}（子项累加，{len(parts)}/{total_subs} 项）",
                    kcal=sum(p.kcal for p in parts),
                    protein=round(sum(p.protein for p in parts), 1),
                    fat=round(sum(p.fat for p in parts), 1),
                    sodium=sum(p.sodium for p in parts),
                )
            elif parts:
                # 覆盖不足：仅作品类参考，不参与热量统计
                o.partial_nutrition = NutritionItem(
                    name=f"{o.product_name}（部分匹配 {len(parts)}/{total_subs}）",
                    kcal=sum(p.kcal for p in parts),
                    protein=round(sum(p.protein for p in parts), 1),
                    fat=round(sum(p.fat for p in parts), 1),
                    sodium=sum(p.sodium for p in parts),
                )
        if o.nutrition is not None:
            matched.append((o, o.nutrition))

        # ---- 品类统计：逐个餐品判定，一单可命中多品类 ----
        for nm in names:
            cat = _category_of(nm)
            if cat:
                cat_hits[cat] += 1

    n = len(ctx.orders)
    prof.category_ratio = {k: v / n for k, v in cat_hits.items()}
    prof.matched_orders = len(matched)

    if matched:
        prof.avg_kcal = sum(m.kcal for _, m in matched) / len(matched)
        prof.avg_protein = sum(m.protein for _, m in matched) / len(matched)
        prof.avg_sodium = sum(m.sodium for _, m in matched) / len(matched)
        prof.high_kcal_ratio = sum(1 for _, m in matched if m.kcal >= 500) / len(matched)
        prof.zero_drink_ratio = sum(1 for _, m in matched if m.kcal <= 150) / len(matched)

    prof.work_hour_ratio = sum(1 for o in ctx.orders if o.is_work_hour) / n
    return prof


def _judge_by_taste(ctx: MMTIContext, prof: TasteProfile,
                    facts: list[str], confidence: str) -> Optional[PersonaVerdict]:
    """基于口味特征判定食欲型 / 身体型 / 心情型人格。

    返回 None 表示未命中，交由上层继续判定。
    """
    # 冷启动保护：订单少于 2 笔时口味特征不可靠（实测踩坑：
    # 真实用户可能只有 0-1 笔订单，此时 16 张人格中有 12 张无法判定）。
    # 宁可不判，也不要用2 笔数据编造结论。
    if prof.total_orders < 2 or prof.matched_orders < 2:
        return None

    cr = prof.category_ratio
    facts_with_taste = facts + [f"口味分布：{_top_category_cn(prof)}"]
    kcal = prof.avg_kcal or 0
    pro = prof.avg_protein or 0

    # ======================================================================
    # 判定顺序说明（依据实测数据标定，勿随意调换）：
    #   1. 品类强特征（儿童餐/派）—— 一票通过
    #   2. 饮品系（燕麦/零糖）    —— 场景明确，不易与其他型混淆
    #   3. 热量分层（绝代双爽/卷王）—— 用绝对 kcal 分层
    #   4. 蛋白与运动场景（平板支撑/摸鱼）—— 需热量条件配合
    #   5. 品类兜底（干饭/急死）  —— 鸡肉/汉堡主导
    #   6. 蛋白底线                —— 最后兜底，避免抢前面类型的判定
    # ======================================================================

    # ---- 1. 心情型：品类强特征 ----
    if cr.get("kids", 0) >= THRESHOLD_MAJORITY:
        return PersonaVerdict(
            PERSONA_MAP["kid"],
            f"你有 {cr['kids']:.0%} 的订单是儿童餐，六十岁也想吃儿童餐",
            facts_with_taste, confidence)
    if cr.get("pie", 0) >= THRESHOLD_SEGMENT:
        return PersonaVerdict(
            PERSONA_MAP["pie"],
            f"你的订单里 {cr['pie']:.0%} 带派，有派才有气氛",
            facts_with_taste, confidence)

    # ---- 2. 身体型：饮品系 ----
    if cr.get("drink", 0) >= THRESHOLD_MAJORITY and 80 <= kcal <= 250:
        return PersonaVerdict(
            PERSONA_MAP["oat"],
            f"{cr['drink']:.0%} 的订单是饮品，平均 {kcal:.0f} kcal，轻盈的一餐",
            facts_with_taste, confidence)
    if prof.zero_drink_ratio >= THRESHOLD_MAJORITY and kcal <= 150:
        return PersonaVerdict(
            PERSONA_MAP["zero"],
            f"你有 {prof.zero_drink_ratio:.0%} 的订单选了 0 卡饮品，快乐不必加糖",
            facts_with_taste, confidence)

    # ---- 3. 食欲型：先按品类，再按热量分层 ----
    # 卷王 vs 绝代双爽 vs 平板支撑三者热量区间重叠，靠品类区分：
    #   卷王=汉堡主导（巨无霸等）；绝代双爽=禽类副食（鸡翅/鸡块）；
    #   平板支撑=汉堡但热量蛋白需在线。
    burger_r = cr.get("burger", 0)
    chicken_r = cr.get("chicken", 0)

    if burger_r >= THRESHOLD_SEGMENT and kcal >= 500:
        return PersonaVerdict(
            PERSONA_MAP["king"],
            f"{burger_r:.0%} 是汉堡，平均 {kcal:.0f} kcal，胃口就是实力",
            facts_with_taste, confidence)
    if chicken_r >= THRESHOLD_MAJORITY and kcal >= 380 and pro >= 25:
        return PersonaVerdict(
            PERSONA_MAP["double"],
            f"{chicken_r:.0%} 是鸡肉，平均 {kcal:.0f} kcal、蛋白 {pro:.0f}g，一口封神",
            facts_with_taste, confidence)
    # 干饭最强音：鸡肉主导但热量中等（鸡排/麦乐鸡类）
    if chicken_r >= THRESHOLD_MAJORITY and 260 <= kcal < 380:
        return PersonaVerdict(
            PERSONA_MAP["biggest"],
            f"{chicken_r:.0%} 是鸡肉，平均 {kcal:.0f} kcal，要点就点最大份",
            facts_with_taste, confidence)
    # 急死汉堡包：汉堡主导、热量中等（下午垫肚子）
    if burger_r >= THRESHOLD_SEGMENT and 200 <= kcal < 350:
        return PersonaVerdict(
            PERSONA_MAP["starving"],
            f"{burger_r:.0%} 是汉堡，平均 {kcal:.0f} kcal，三点半就饿了",
            facts_with_taste, confidence)

    # ---- 4. 蛋白与运动场景 ----
    if pro >= 20 and kcal >= 400:
        return PersonaVerdict(
            PERSONA_MAP["plank"],
            f"你的订单平均 {kcal:.0f} kcal、蛋白 {pro:.0f}g，热量蛋白都在线",
            facts_with_taste, confidence)
    if cr.get("roll", 0) >= THRESHOLD_MAJORITY or prof.work_hour_ratio >= THRESHOLD_WORK_HOUR:
        detail = (f"{cr['roll']:.0%} 的订单是卷类" if cr.get("roll", 0) >= THRESHOLD_MAJORITY
                  else f"{prof.work_hour_ratio:.0%} 的订单下在工作日 10-17 点")
        return PersonaVerdict(
            PERSONA_MAP["slacker"],
            f"{detail}，上班的一点慰藉",
            facts_with_taste, confidence)

    # ---- 6. 蛋白底线：最后兜底 ----
    # 放在最后是必要的：实测中该规则门槛（蛋白>=12 且热量<400）会抢走
    # 卷王、干饭最强音等食欲型判定，必须作为兜底而非主判据。
    if pro >= 12:
        return PersonaVerdict(
            PERSONA_MAP["protein"],
            f"你的订单平均蛋白 {pro:.0f}g，别的都能省，蛋白不能",
            facts_with_taste, confidence)

    return None


def _top_category_cn(prof: TasteProfile) -> str:
    """把品类占比转成中文描述，用于事实展示。"""
    cn = {"burger": "汉堡", "chicken": "鸡肉", "fish": "鱼", "pie": "派",
          "kids": "儿童餐", "roll": "卷", "drink": "饮品", "dessert": "甜品"}
    items = sorted(prof.category_ratio.items(), key=lambda x: -x[1])
    return " ".join(f"{cn.get(k, k)}{v:.0%}" for k, v in items if v > 0) or "暂无数据"


def judge_persona(ctx: MMTIContext) -> PersonaVerdict:
    """MMTI 人格判定主函数。

    判定优先级（自上而下，命中即停）：
      0. 深夜强信号（22 点后）
      1. 券时段轮转
      2. 口味特征分析（食欲型 / 身体型 / 心情型）
      3. 积分行为
      4. 券过期提醒
      5. 复购集中
      6. 默认随性真香派
    """
    now = ctx.now
    facts: list[str] = []

    # ---- 收集第二段事实数据（全部来自 MCP 真实返回）----
    if ctx.orders:
        names = [o.product_name for o in ctx.orders]
        cities = {o.store_name.split("市")[0] for o in ctx.orders}
        avg = sum(o.amount_cny for o in ctx.orders) / len(ctx.orders)
        facts.append(f"{len(ctx.orders)} 笔订单全是{names[0]}")
        facts.append(f"跨 {len(cities)} 城 {len(ctx.orders)} 店")
        facts.append(f"均价 {avg:.1f} 元")
    if ctx.coupons:
        facts.append(f"{len(ctx.coupons)} 张券待规划")
    confidence = "高" if len(ctx.orders) >= 3 else ("中" if ctx.orders else "低")

    # ---- 0. 深夜强信号优先（夜宵场景人格由时段决定，优先于券）----
    if now.hour >= 22:
        return PersonaVerdict(
            PERSONA_MAP["midnight"],
            f"现在 {now:%H:%M}，热朱古力 125 kcal，深夜给胃一个拥抱",
            facts,
            confidence,
        )

    # ---- 1. 券时段轮转 ----
    active = [c for c in ctx.coupons if c.active_at(now)]
    if active:
        c = active[0]
        is_breakfast = c.start_hour <= now.hour < 11
        if is_breakfast:
            return PersonaVerdict(
                PERSONA_MAP["perfect"],
                f"现在 {now:%H:%M}，你的「{c.title}」券（¥{c.price_cny:g}）只在"
                f"05:00-10:29 有效，一顿饭也要满分",
                [f"{c.title} ¥{c.price_cny:g}" for c in active] + facts,
                confidence,
            )
        return PersonaVerdict(
            PERSONA_MAP["coupon"],
            f"你有 {len(active)} 张券现在就能用，其中「{c.title}」¥{c.price_cny:g}，"
            f"{c.end:%H:%M} 前用掉最划算",
            [f"{c.title} ¥{c.price_cny:g}" for c in active] + facts,
            confidence,
        )

    # ---- 2. 口味特征分析（食欲型 / 身体型 / 心情型）----
    prof = build_taste_profile(ctx)
    verdict = _judge_by_taste(ctx, prof, facts, confidence)
    if verdict is not None:
        return verdict

    # ---- 3. 积分行为 ----
    if ctx.points and ctx.lottery:
        times = int(ctx.points.available // ctx.lottery.draw_point)
        if times > 0:
            return PersonaVerdict(
                PERSONA_MAP["points"],
                f"你还有 {ctx.points.available:g} {ctx.points.currency}，"
                f"够抽 {times} 次，奖品池里有{ctx.lottery.best_prize}",
                [
                    f"可用积分 {ctx.points.available:g}",
                    f"累计 {ctx.points.accumulated:g} / 已用 {ctx.points.used:g}",
                    f"已过期 {ctx.points.expired:g}",
                ] + facts,
                confidence,
            )

    # ---- 3. 券即将过期 ----
    today_expiring = [c for c in ctx.coupons if c.expires_today(now)]
    if today_expiring:
        titles = "、".join(c.title for c in today_expiring[:2])
        return PersonaVerdict(
            PERSONA_MAP["coupon"],
            f"你有 {len(today_expiring)} 张券今天就到期（{titles}），别让它白放着",
            [f"{c.title} 今日到期" for c in today_expiring] + facts,
            confidence,
        )

    # ---- 4. 复购集中 ----
    if ctx.orders:
        return PersonaVerdict(
            PERSONA_MAP["random"],
            f"你最近 {len(ctx.orders)} 笔订单都是同一个选择，闭眼点就对",
            facts,
            confidence,
        )

    # ---- 5. 冷启动：无数据或数据不足，明确告知并引导自选 ----
    # 不编造结论——口味人格需2 笔以上订单才可靠（实测踩坑）。
    return PersonaVerdict(
        PERSONA_MAP["random"],
        "还没有足够的订单数据，口味人格需要 2 笔以上订单才能判定。"
        "你可以直接从 16 张人格里选一张，我按那张推荐。",
        facts or ["暂无订单数据"],
        "低",
    )


def persona_timeline(ctx: MMTIContext) -> list[tuple[str, str]]:
    """生成今日人格轨迹。演示一天内多次轮转。"""
    out: list[tuple[str, str]] = []
    for hour in (6, 12, 18, 22):
        probe = ctx.now.replace(hour=hour, minute=30)
        sub = MMTIContext(now=probe, coupons=ctx.coupons,
                          orders=ctx.orders, points=ctx.points, lottery=ctx.lottery)
        out.append((f"{hour:02d}:30", judge_persona(sub).persona.name))
    return out


# ============================================================================
# 四、人格卡输出（三段式）
# ============================================================================


def _w(s: str) -> int:
    """计算字符串的终端显示宽度（CJK 字符占 2 列）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def _row(s: str = "", width: int = 33) -> str:
    """生成一行对齐的卡片边框内容。"""
    return f"| {s.ljust(width)} |"


def render_card(v: PersonaVerdict) -> str:
    """三段式人格卡：是谁 / 多准 / 是什么。

    使用东���宽度对齐，保证中英文混排时边框不歪。
    """
    p = v.persona
    w = 33
    bar = "+" + "-" * (w + 2) + "+"
    lines = [
        bar,
        _row("MMTI · 系统判定，可推翻", w),
        _row("", w),
        _row(p.name.center(w + (_w(p.name) - 0) // 2 - _w(p.name) % 2), w),
        _row(v.family_tagline.center(w + (len(v.family_tagline) - _w(v.family_tagline))), w),
        _row("", w),
    ]
    for f in v.facts[:4]:
        lines.append(_row(f[:w], w))
    lines += [
        _row("", w),
        _row(p.tagline[:w], w),
        _row("可切换或自选 16 张人格", w),
        bar,
    ]
    return "\n".join(lines)


def list_personas() -> str:
    """列出全部 16 型人格。"""
    out: list[str] = []
    for fam in (FAMILY_APPETITE, FAMILY_BRAIN, FAMILY_BODY, FAMILY_MOOD):
        out.append(f"\n{fam} · {FAMILY_TAGLINE[fam]}")
        for p in PERSONAS:
            if p.family == fam:
                out.append(f"  [{p.key:<8}] {p.name:<6} ← {p.homophone_from}")
                out.append(f"{'':<13}{p.tagline}")
    return "\n".join(out)


# ============================================================================
# 五、Demo 数据（采样自 MCP 实测返回）
# ============================================================================

# 营养库样本：采样自 list-nutrition-foods 实测返回（160 款中选取人格相关条目）
NUTRITION_SAMPLE: list[NutritionItem] = [
    NutritionItem("巨无霸", 513, 27, 26, 961),
    NutritionItem("麦辣鸡腿汉堡", 485, 24, 24, 1208),
    NutritionItem("板烧鸡腿堡", 391, 23, 17, 1041),
    NutritionItem("吉士汉堡包", 294, 16, 12, 673),
    NutritionItem("汉堡包", 248, 13, 8, 492),
    NutritionItem("那么大鸡排", 385, 24, 21, 996),
    NutritionItem("绝代双翅", 469, 32, 27, 1167),
    NutritionItem("麦乐鸡5块", 213, 12, 12, 422),
    NutritionItem("麦香鸡", 369, 15, 17, 731),
    NutritionItem("麦香鱼", 325, 16, 13, 556),
    NutritionItem("儿童鱼排堡", 269, 15, 6, 442),
    NutritionItem("香芋派", 232, 2, 12, 159),
    NutritionItem("菠萝派", 221, 2, 11, 147),
    NutritionItem("麦麦趣鸡球", 266, 17, 13, 789),
    NutritionItem("酥酥多笋卷", 342, 14, 15, 1044),
    NutritionItem("图林根香肠早安营养卷", 425, 14, 23, 977),
    NutritionItem("火腿扒早安营养卷", 444, 16, 24, 1065),
    NutritionItem("苹板支撑Pro", 476, 25, 18, 1077),
    NutritionItem("牛气满满", 495, 26, 24, 764),
    NutritionItem("培根安格斯厚牛堡", 707, 34, 44, 1037),
    NutritionItem("芝士双层安格斯厚牛堡", 1003, 58, 65, 1373),
    NutritionItem("双层深海鳕鱼堡", 485, 28, 21, 917),
    NutritionItem("麦满分（猪柳蛋）", 387, 23, 21, 846),
    NutritionItem("双层猪柳蛋麦满分", 513, 29, 32, 1210),
    NutritionItem("无糖可口可乐中杯", 0, 0, 0, 35),
    NutritionItem("无糖可口可乐大杯", 0, 0, 0, 53),
    NutritionItem("冰燕麦奶铁中杯", 132, 3, 5, 87),
    NutritionItem("热燕麦奶铁大杯", 222, 5, 8, 152),
    NutritionItem("纯牛奶（盒装）", 129, 7, 7, 73),
    NutritionItem("热牛奶大杯", 240, 13, 11, 137),
    NutritionItem("冰美式中杯", 13, 1, 0, 0),
    NutritionItem("热朱古力", 125, 2, 2, 107),
    NutritionItem("圆筒冰淇淋", 93, 2, 3, 36),
    NutritionItem("中薯条", 289, 4, 12, 165),
    NutritionItem("小薯条", 210, 3, 9, 120),
    NutritionItem("可口可乐中杯", 147, 0, 0, 0),
    # 套餐子项常见品（补全以提升子项匹配覆盖率）
    NutritionItem("高达吉士双牛堡", 476, 25, 18, 1077),
    NutritionItem("吉士双牛堡", 466, 24, 18, 1005),
    NutritionItem("可乐麦炫酷", 105, 0, 0, 0),
    NutritionItem("无糖可乐麦炫酷", 0, 0, 0, 0),
    NutritionItem("雪碧麦炫酷", 96, 0, 0, 0),
    NutritionItem("麦趣鸡球", 266, 17, 13, 789),
    NutritionItem("鸡腿堡（经典）", 391, 23, 17, 1041),
    NutritionItem("上校鸡块", 232, 14, 15, 470),
]


def build_demo_context(now: datetime) -> MMTIContext:
    """构造一份采样自 MCP 实测返回的演示上下文。

    数据来源：
      - 券：query-my-coupons 实测返回（14 张，节选）
      - 订单：order-list 实测返回（3 笔，含套餐子项）
      - 积分：query-my-account 实测返回
      - 抽奖：query-lottery-info 实测返回（单次 24 积分）
      - 营养：list-nutrition-foods 实测返回（160 款，节选 32 款）
    """
    return MMTIContext(
        now=now,
        nutrition=NUTRITION_SAMPLE,
        coupons=[
            # 早餐券：实测返回中每个工作日各有一张 ¥9.9 早餐两件套，05:00-10:29
            Coupon("火腿扒堡早餐两件套", 9.9, datetime(2026, 10, 9, 5, 0),
                   datetime(2026, 10, 9, 10, 29), (4,), 5, 11, dine_in_only=True),
            Coupon("麦旋风任选", 9.9, datetime(2026, 10, 5, 10, 30),
                   datetime(2026, 10, 9, 23, 59), (0, 1, 2, 3, 4), 10, 24),
            Coupon("薯薯任选", 9.9, datetime(2026, 10, 5, 10, 30),
                   datetime(2026, 10, 9, 23, 59), (0, 1, 2, 3, 4), 10, 24),
            Coupon("巧克力味厚松饼猪柳蛋套餐", 29.9, datetime(2026, 10, 10, 5, 0),
                   datetime(2026, 10, 10, 10, 29), (5,), 5, 11, dine_in_only=True),
        ],
        orders=[
            Order("1030748720000571936950761192",
                  datetime(2026, 8, 15, 12, 26),
                  "精选超值随心配", "9900013291", 13.9,
                  "麦当劳深圳国银金融中心餐厅",
                  combo_items=[OrderItem("那么大鸡排（椒盐风味）", "521156"),
                               OrderItem("可乐麦炫酷", "521328")]),
            Order("1030561090000571241233166421",
                  datetime(2026, 7, 15, 17, 47),
                  "精选超值随心配", "9900013291", 13.9,
                  "麦当劳佛山乐从裕和路金海文化创意中心餐厅",
                  combo_items=[OrderItem("高达吉士双牛堡", "521316"),
                               OrderItem("无糖可口可乐中杯", "3071")]),
            Order("1030877110000570479337860051",
                  datetime(2026, 6, 10, 12, 3),
                  "精选超值随心配", "9900013291", 18.9,
                  "麦当劳广州英雄广场餐厅(烈士陵园地铁A出口)",
                  combo_items=[OrderItem("那么大鸡排（椒盐风味）", "521156"),
                               OrderItem("小薯条", "4800"),
                               OrderItem("圆筒冰淇淋", "515837"),
                               OrderItem("无糖可乐麦炫酷", "521329")]),
        ],
        points=PointAccount(available=56.5, accumulated=927,
                            used=564, expired=306.5),
        lottery=Lottery(draw_point=24, best_prize="板烧三件套5折券"),
    )


# ============================================================================
# 六、判定覆盖率自测
# ============================================================================


def _synth_orders(plan: list[tuple[str, str, int]]) -> list[Order]:
    """按 (餐品名, 下单时间, 金额) 构造合成订单，仅用于覆盖率自测。

    模拟真实场景的两接口关联：按餐品名到NUTRITION_SAMPLE 查营养条目，
    并挂到 order.nutrition 上，供 build_taste_profile 统计。
    这些订单不是真实用户数据，仅验证判定规则是否可触达。
    """
    index = {n.name: n for n in NUTRITION_SAMPLE}
    return [
        Order(f"SYNTH{i:04d}", datetime.strptime(t, "%Y-%m-%d %H:%M"),
              name, "SYNTH", amount, f"合成门店{i}",
              nutrition=index.get(name))
        for i, (name, t, amount) in enumerate(plan)
    ]


# 覆盖 16 张人格的构造样本：(人格 key, 订单列表, 券列表, 时间)
COVERAGE_CASES: list[tuple[str, list[tuple[str, str, int]]]] = [
    # 食欲型
    ("king", [("巨无霸", "2026-08-01 12:30", 35.0),
              ("麦辣鸡腿汉堡", "2026-08-03 12:40", 32.0),
              ("芝士双层安格斯厚牛堡", "2026-08-05 12:30", 45.0),
              ("双层深海鳕鱼堡", "2026-08-08 12:20", 38.0)]),
    ("biggest", [("那么大鸡排", "2026-08-01 12:30", 25.0),
                 ("麦乐鸡5块", "2026-08-03 12:40", 22.0),
                 ("麦麦脆汁鸡-琵琶腿", "2026-08-05 12:30", 28.0)]),
    ("double", [("绝代双翅", "2026-08-01 20:10", 30.0),
                ("绝代双翅", "2026-08-03 20:20", 30.0),
                ("麦乐鸡5块", "2026-08-05 20:30", 26.0),
                ("那么大鸡排", "2026-08-08 20:00", 25.0)]),
    ("starving", [("吉士汉堡包", "2026-08-01 15:30", 15.0),
                  ("汉堡包", "2026-08-03 16:20", 12.0),
                  ("麦香鱼", "2026-08-05 15:40", 18.0)]),
    # 身体型
    ("plank", [("苹板支撑Pro", "2026-08-01 12:30", 29.9),
               ("牛气满满", "2026-08-03 12:40", 28.0),
               ("双层深海鳕鱼堡", "2026-08-05 12:30", 32.0)]),
    ("oat", [("冰燕麦奶铁中杯", "2026-08-01 15:30", 14.0),
             ("热燕麦奶铁大杯", "2026-08-03 15:40", 17.0),
             ("冰燕麦奶铁中杯", "2026-08-05 15:30", 14.0)]),
    ("zero", [("无糖可口可乐大杯", "2026-08-01 12:30", 9.0),
              ("无糖可口可乐中杯", "2026-08-03 12:40", 8.0),
              ("无糖可口可乐大杯", "2026-08-05 12:30", 9.0),
              ("冰美式中杯", "2026-08-07 15:00", 10.0)]),
    ("protein", [("纯牛奶（盒装）", "2026-08-01 08:20", 9.0),
                 ("热牛奶大杯", "2026-08-03 08:30", 12.0),
                 ("麦满分（猪柳蛋）", "2026-08-05 08:10", 22.0)]),
    # 心情型
    ("kid", [("儿童鱼排堡", "2026-08-01 12:30", 18.0),
             ("儿童鱼排堡", "2026-08-03 12:40", 18.0),
             ("儿童鱼排堡", "2026-08-05 12:30", 18.0),
             ("麦香鱼", "2026-08-07 18:00", 22.0)]),
    ("pie", [("香芋派", "2026-08-01 15:30", 8.0),
             ("菠萝派", "2026-08-03 15:40", 8.0),
             ("香芋派", "2026-08-05 15:30", 8.0),
             ("圆筒冰淇淋", "2026-08-07 20:00", 8.0)]),
    ("slacker", [("酥酥多笋卷", "2026-08-03 10:30", 12.0),
                  ("图林根香肠早安营养卷", "2026-08-04 11:20", 15.0),
                  ("火腿扒早安营养卷", "2026-08-05 14:30", 16.0),
                  ("麦麦趣鸡球", "2026-08-06 16:00", 14.0)]),
]

# 券与时段驱动的 5 张
COVERAGE_TIMED: list[tuple[str, datetime, list[Coupon]]] = [
    ("perfect", datetime(2026, 10, 9, 7, 30), [
        Coupon("火腿扒堡早餐两件套", 9.9, datetime(2026, 10, 9, 5, 0),
               datetime(2026, 10, 9, 10, 29), (4,), 5, 11)]),
    ("coupon", datetime(2026, 10, 9, 21, 5), [
        Coupon("麦旋风任选", 9.9, datetime(2026, 10, 5, 10, 30),
               datetime(2026, 10, 9, 23, 59), (0, 1, 2, 3, 4), 10, 24)]),
    ("midnight", datetime(2026, 10, 9, 22, 30), []),
    ("points", datetime(2026, 10, 9, 15, 0), []),
    ("random", datetime(2026, 10, 9, 15, 0), []),
]


def run_coverage_test() -> None:
    """验证 16 张人格是否全部可被判定规则触达。"""
    print("=" * 52)
    print("MMTI 人格判定覆盖率自测")
    print("=" * 52)

    results: dict[str, str] = {}

    # 券 / 时段 / 积分 / 默认 驱动的 5 张
    for key, now, coupons in COVERAGE_TIMED:
        pts = PointAccount(56.5, 927, 564, 306.5) if key == "points" else None
        lot = Lottery(24, "板烧三件套5折券") if key == "points" else None
        ctx = MMTIContext(now=now, coupons=coupons, points=pts, lottery=lot)
        results[key] = judge_persona(ctx).persona.key

    # 口味特征驱动的 11 张
    for key, plan in COVERAGE_CASES:
        ctx = MMTIContext(now=datetime(2026, 10, 9, 14, 0),
                          orders=_synth_orders(plan), nutrition=NUTRITION_SAMPLE)
        results[key] = judge_persona(ctx).persona.key

    # 汇总
    ok = 0
    print(f"\n{'人格 key':<12}{'预期':<12}{'实际':<12}{'结果'}")
    print("-" * 52)
    for key in [k for k, _, _ in COVERAGE_TIMED] + [k for k, _ in COVERAGE_CASES]:
        actual = results.get(key, "-")
        good = actual == key
        ok += good
        print(f"{key:<12}{key:<12}{actual:<12}{'PASS' if good else 'FAIL'}")
    print("-" * 52)
    print(f"\n覆盖率：{ok}/16")
    if ok == 16:
        print("全部人格均可被判定规则触达。")
    else:
        failed = [k for k in results if results[k] != k]
        print(f"未触达或错判：{', '.join(failed)}")
    print("\n说明：合成订单仅用于规则自测，不含真实用户数据。\n")


# ============================================================================
# 七、CLI
# ============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mmti",
        description="麦麦人格 MMTI - 人格判定引擎 Demo",
    )
    parser.add_argument("--now", help="模拟时间，格式 YYYY-MM-DDTHH:MM，默认当前时间")
    parser.add_argument("--list", action="store_true", help="列出全部 16 型人格")
    parser.add_argument("--timeline", action="store_true", help="输出今日人格轨迹")
    parser.add_argument("--coverage", action="store_true",
                        help="自测：验证 16 张人格是否均可被判定触达")
    args = parser.parse_args()

    if args.list:
        print(list_personas())
        return

    if args.coverage:
        run_coverage_test()
        return

    now = (datetime.fromisoformat(args.now) if args.now else datetime.now())
    ctx = build_demo_context(now)
    verdict = judge_persona(ctx)

    print()
    print("麦麦人格 MMTI · McDonald's Mood & Taste Index")
    print("=" * 40)
    print(f"\n判定时刻：{now:%Y-%m-%d %H:%M}（{now:%A}）")
    print(f"数据来源：麦当劳 MCP 实测采样数据\n")
    print(render_card(verdict))
    print(f"\n判定依据：{verdict.reason}")
    print(f"数据置信度：{verdict.confidence}")

    if args.timeline:
        print("\n今日人格轨迹")
        print("-" * 30)
        for t, name in persona_timeline(ctx):
            print(f"  {t}  {name}")

    print("\n提示：以上餐品与价格以麦当劳官方实时数据为准。")
    print("      热量与钠含量为信息参考，不构成医疗或营养诊断。\n")


if __name__ == "__main__":
    main()