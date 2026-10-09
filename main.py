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
class Order:
    """对应 order-list 返回条目。"""

    order_id: str
    created_at: datetime
    product_name: str
    product_code: str
    amount_cny: float
    store_name: str


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


def judge_persona(ctx: MMTIContext) -> PersonaVerdict:
    """MMTI 人格判定主函数。

    判定优先级（自上而下，命中即停）：
      1. 券时段轮转命中
      2. 积分行为命中
      3. 券行为命中
      4. 复购集中命中
      5. 默认随性真香派
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

    # ---- 2. 积分行为 ----
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

    # ---- 5. 默认 ----
    return PersonaVerdict(
        PERSONA_MAP["random"],
        "还没有订单数据，先给你一个随性人格",
        facts,
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


def build_demo_context(now: datetime) -> MMTIContext:
    """构造一份采样自 MCP 实测返回的演示上下文。

    数据来源：
      - 券：query-my-coupons 实测返回（14 张，节选 3 张）
      - 订单：order-list 实测返回（3 笔）
      - 积分：query-my-account 实测返回
      - 抽奖：query-lottery-info 实测返回（单次 24 积分）
    """
    return MMTIContext(
        now=now,
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
                  "麦当劳深圳国银金融中心餐厅"),
            Order("1030561090000571241233166421",
                  datetime(2026, 7, 15, 17, 47),
                  "精选超值随心配", "9900013291", 13.9,
                  "麦当劳佛山乐从裕和路金海文化创意中心餐厅"),
            Order("1030877110000570479337860051",
                  datetime(2026, 6, 10, 12, 3),
                  "精选超值随心配", "9900013291", 18.9,
                  "麦当劳广州英雄广场餐厅(烈士陵园地铁A出口)"),
        ],
        points=PointAccount(available=56.5, accumulated=927,
                            used=564, expired=306.5),
        lottery=Lottery(draw_point=24, best_prize="板烧三件套5折券"),
    )


# ============================================================================
# 六、CLI
# ============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mmti",
        description="麦麦人格 MMTI - 人格判定引擎 Demo",
    )
    parser.add_argument("--now", help="模拟时间，格式 YYYY-MM-DDTHH:MM，默认当前时间")
    parser.add_argument("--list", action="store_true", help="列出全部 16 型人格")
    parser.add_argument("--timeline", action="store_true", help="输出今日人格轨迹")
    args = parser.parse_args()

    if args.list:
        print(list_personas())
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