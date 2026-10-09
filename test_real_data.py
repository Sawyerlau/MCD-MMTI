"""真实数据回归测试：用 list-nutrition-foods 实际返回的品名验证匹配行为。

这个测试的价值在于：合成样本用的是标准品名，而真实订单里大量使用
营销名与套餐子项名，两者的匹配行为差异极大。

覆盖三个场景：
  1. 带括号/营销词的子项应能匹配（「那么大鸡排（椒盐风味）」）
  2. 营养库确实没有的品名应如实报缺口，不硬凑（「高达吉士双牛堡」）
  3. 未标注杯型的饮品应报缺口而非猜规格（「可乐麦炫酷」）
"""

from datetime import datetime

import main

# 直接取自 list-nutrition-foods 实测返回的关键条目
REAL_NUTRITION = [
    main.NutritionItem("巨无霸", 513, 27, 26, 961),
    main.NutritionItem("板烧鸡腿堡", 391, 23, 17, 1041),
    main.NutritionItem("吉士汉堡包", 294, 16, 12, 673),
    main.NutritionItem("双层吉士汉堡", 429, 27, 22, 1017),
    main.NutritionItem("麦香鱼", 325, 16, 13, 556),
    main.NutritionItem("儿童鱼排堡", 269, 15, 6, 442),
    main.NutritionItem("那么大鸡排", 385, 24, 21, 996),
    main.NutritionItem("绝代双翅", 469, 32, 27, 1167),
    main.NutritionItem("麦乐鸡5块", 213, 12, 12, 422),
    main.NutritionItem("香芋派", 232, 2, 12, 159),
    main.NutritionItem("圆筒冰淇淋", 93, 2, 3, 36),
    main.NutritionItem("小薯条", 210, 3, 9, 120),
    main.NutritionItem("热朱古力", 125, 2, 2, 107),
    main.NutritionItem("纯牛奶（盒装）", 129, 7, 7, 73),
    main.NutritionItem("无糖可口可乐中杯", 0, 0, 0, 35),
    main.NutritionItem("无糖可口可乐大杯", 0, 0, 0, 53),
    main.NutritionItem("可乐中杯", 147, 0, 0, 0),
    main.NutritionItem("可乐大杯", 224, 0, 0, 0),
    main.NutritionItem("冰燕麦奶铁中杯", 132, 3, 5, 87),
    main.NutritionItem("“苹板”支撑Pro", 476, 25, 18, 1077),
    main.NutritionItem("牛气满满", 495, 26, 24, 764),
    main.NutritionItem("麦麦趣鸡球", 266, 17, 13, 789),
    main.NutritionItem("酥酥多笋卷", 342, 14, 15, 1044),
    main.NutritionItem("图林根香肠早安营养卷", 425, 14, 23, 977),
    main.NutritionItem("双层猪柳蛋麦满分", 513, 29, 32, 1210),
]


def _real_orders() -> list[main.Order]:
    """order-list 实测返回的三笔订单（含套餐子项）。"""
    raw = [
        ("2026-08-15 12:26:40", "精选超值随心配", 13.9, "深圳国银金融中心餐厅",
         [("那么大鸡排（椒盐风味）", 1), ("可乐麦炫酷", 1)]),
        ("2026-07-15 17:47:49", "精选超值随心配", 13.9, "佛山乐从金海创意中心餐厅",
         [("高达吉士双牛堡", 1), ("无糖可口可乐中杯", 1)]),
        ("2026-06-10 12:03:31", "精选超值随心配", 18.9, "广州英雄广场餐厅",
         [("小薯条", 1), ("那么大鸡排（椒盐风味）", 1),
          ("圆筒冰淇淋", 1), ("无糖可乐麦炫酷", 1)]),
    ]
    return [
        main.Order(f"R{i}", datetime.strptime(t, "%Y-%m-%d %H:%M:%S"),
                   name, "9900013291", amt, store,
                   combo_items=[main.OrderItem(n, "", q) for n, q in subs])
        for i, (t, name, amt, store, subs) in enumerate(raw)
    ]


def test_bracket_and_marketing_names_match() -> None:
    """带括号与营销词的子项应能匹配到标准品名。"""
    idx = {main._norm(n.name): n for n in REAL_NUTRITION}
    hit = main._match_nutrition("那么大鸡排（椒盐风味）", idx)
    assert hit is not None, "带括号的子项应能匹配"
    assert hit.kcal == 385, f"热量应为 385，实际 {hit.kcal}"
    print("✓ 带括号子项匹配正确（那么大鸡排（椒盐风味）→ 385 kcal）")


def test_quoted_name_matches() -> None:
    """营养库中带中文引号的品名应能匹配去引号后的写法。"""
    idx = {main._norm(n.name): n for n in REAL_NUTRITION}
    hit = main._match_nutrition("苹板支撑Pro", idx)
    assert hit is not None, "带引号的库品名应能匹配"
    assert hit.kcal == 476, f"热量应为 476，实际 {hit.kcal}"
    print("✓ 引号品名匹配正确（苹板支撑Pro → “苹板”支撑Pro，476 kcal）")


def test_absent_name_reported_as_gap() -> None:
    """营养库确实没有的品名应报缺口，不硬凑。"""
    idx = {main._norm(n.name): n for n in REAL_NUTRITION}
    assert main._match_nutrition("高达吉士双牛堡", idx) is None, \
        "库里无此品名，不应硬匹配"
    print("✓ 缺失品名如实报缺口（高达吉士双牛堡）")


def test_size_unspecified_drink_reported_as_gap() -> None:
    """未标注杯型的饮品应报缺口，而非猜一个规格。"""
    idx = {main._norm(n.name): n for n in REAL_NUTRITION}
    assert main._match_nutrition("可乐麦炫酷", idx) is None, \
        "未标注杯型时不应猜测规格"
    print("✓ 未标注杯型如实报缺口（可乐麦炫酷）")


def test_gaps_surfaced_on_card() -> None:
    """缺口必须显示在人格卡上，而不是只存在于内部状态。"""
    ctx = main.MMTIContext(now=datetime(2026, 10, 9, 15, 0),
                           orders=_real_orders(), nutrition=REAL_NUTRITION)
    prof = main.build_taste_profile(ctx)
    verdict = main.judge_persona(ctx)

    assert prof.missing_items, "应识别出数据缺口"
    assert "高达吉士双牛堡" in prof.missing_items
    assert "可乐麦炫酷" in prof.missing_items
    assert "精选超值随心配" not in prof.missing_items, \
        "套餐主品是容器，不应算作缺口"

    assert verdict.data_gaps == prof.missing_items, \
        "缺口应注入到 verdict（实测踩坑：走复购分支时曾遗漏）"
    card = main.render_card(verdict)
    assert "营养数据缺失" in card, "人格卡应显示缺口提示"
    print(f"✓ 缺口已显示在人格卡上（{len(prof.missing_items)} 项）")


def run_all() -> None:
    print("=" * 52)
    print("真实数据回归测试")
    print("=" * 52)
    for fn in (test_bracket_and_marketing_names_match,
               test_quoted_name_matches,
               test_absent_name_reported_as_gap,
               test_size_unspecified_drink_reported_as_gap,
               test_gaps_surfaced_on_card):
        fn()
    print("\n全部通过。")


if __name__ == "__main__":
    run_all()