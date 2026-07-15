from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph


PAGE_W, PAGE_H = A4
OUT = Path(__file__).resolve().parents[1] / "output/pdf/Scope-Time-State_Solution_CN.pdf"

NAVY = colors.HexColor("#1C4266")
TEXT = colors.HexColor("#24384D")
MUTED = colors.HexColor("#63758A")
LIGHT = colors.HexColor("#F3F6F9")
PALE = colors.HexColor("#EDF7F5")
GOLD = colors.HexColor("#E8B83F")
TEAL = colors.HexColor("#2AA193")
GRID = colors.HexColor("#CBD8E3")

FONT = "STSong-Light"
pdfmetrics.registerFont(UnicodeCIDFont(FONT))


def style(name: str, size: float, leading: float, color=TEXT, align=TA_LEFT) -> ParagraphStyle:
    return ParagraphStyle(
        name=name,
        fontName=FONT,
        fontSize=size,
        leading=leading,
        textColor=color,
        alignment=align,
        spaceAfter=0,
        spaceBefore=0,
    )


def draw_para(c: canvas.Canvas, text: str, x: float, top: float, width: float, size=12, leading=18, color=TEXT, align=TA_LEFT) -> float:
    p = Paragraph(text, style(f"p-{x}-{top}-{size}", size, leading, color, align))
    _, height = p.wrap(width, PAGE_H)
    p.drawOn(c, x, top - height)
    return height


def footer(c: canvas.Canvas, page: int) -> None:
    y = 31 * mm
    c.setStrokeColor(GRID)
    c.setLineWidth(0.6)
    c.line(28 * mm, y, PAGE_W - 28 * mm, y)
    draw_para(c, "Scope-Time-State Memory Graph | Solution", 28 * mm, y - 5, 110 * mm, 8.5, 11, MUTED)
    draw_para(c, str(page), PAGE_W - 40 * mm, y - 5, 12 * mm, 8.5, 11, MUTED, TA_CENTER)


def section_title(c: canvas.Canvas, number: str, title: str, subtitle: str | None = None) -> float:
    top = PAGE_H - 36 * mm
    draw_para(c, f"{number}. {title}", 31 * mm, top, PAGE_W - 62 * mm, 22, 28, NAVY)
    if subtitle:
        draw_para(c, subtitle, 31 * mm, top - 34, PAGE_W - 62 * mm, 11.5, 18, MUTED)
    return top


def callout(c: canvas.Canvas, text: str, x: float, y: float, w: float, h: float, fill=PALE) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(GOLD)
    c.setLineWidth(0.8)
    c.roundRect(x, y, w, h, 2, fill=1, stroke=1)
    c.setFillColor(TEAL)
    c.roundRect(x, y, 3.2, h, 1.5, fill=1, stroke=0)
    draw_para(c, text, x + 14, y + h - 14, w - 28, 12.5, 20, NAVY)


def flow_box(c: canvas.Canvas, x: float, y: float, w: float, h: float, title: str, subtitle: str = "") -> None:
    c.setFillColor(LIGHT)
    c.setStrokeColor(GRID)
    c.setLineWidth(0.8)
    c.rect(x, y, w, h, fill=1, stroke=1)
    title_h = draw_para(c, title, x + 8, y + h / 2 + 14, w - 16, 12.5, 17, NAVY, TA_CENTER)
    if subtitle:
        draw_para(c, subtitle, x + 8, y + h / 2 - title_h + 8, w - 16, 9.5, 13, MUTED, TA_CENTER)


def arrow(c: canvas.Canvas, x1: float, x2: float, y: float) -> None:
    c.setStrokeColor(NAVY)
    c.setFillColor(NAVY)
    c.setLineWidth(0.8)
    c.line(x1, y, x2 - 5, y)
    c.line(x2 - 5, y, x2 - 10, y + 4)
    c.line(x2 - 5, y, x2 - 10, y - 4)


def bullet_list(c: canvas.Canvas, rows: Iterable[str], x: float, top: float, width: float, size=11.5, leading=19, gap=10) -> float:
    current = top
    for row in rows:
        height = draw_para(c, f"- {row}", x, current, width, size, leading, TEXT)
        current -= height + gap
    return current


def simple_table(c: canvas.Canvas, x: float, top: float, widths: Sequence[float], rows: Sequence[Sequence[str]], row_h: float, header=True, font_size=10.5) -> float:
    total_w = sum(widths)
    y = top
    for row_index, row in enumerate(rows):
        y -= row_h
        is_header = header and row_index == 0
        c.setFillColor(NAVY if is_header else (LIGHT if row_index % 2 == 0 else colors.white))
        c.setStrokeColor(GRID)
        c.setLineWidth(0.6)
        c.rect(x, y, total_w, row_h, fill=1, stroke=1)
        cursor = x
        for col_index, (cell, width) in enumerate(zip(row, widths)):
            if col_index:
                c.line(cursor, y, cursor, y + row_h)
            draw_para(c, cell, cursor + 7, y + row_h - 8, width - 14, font_size if not is_header else 10.5, 15, colors.white if is_header else TEXT)
            cursor += width
    return y


def page_one(c: canvas.Canvas) -> None:
    draw_para(c, "Scope-Time-State", 31 * mm, PAGE_H - 58 * mm, 150 * mm, 31, 38, NAVY)
    draw_para(c, "Memory Graph", 31 * mm, PAGE_H - 82 * mm, 150 * mm, 31, 38, NAVY)
    draw_para(c, "长期记忆问答的 Solution 说明", 32 * mm, PAGE_H - 109 * mm, 150 * mm, 14, 20, MUTED)

    callout(
        c,
        "核心命题：长期记忆问答不是从历史中找一段相关文本，而是在正确的 Scope、Time 与 State 约束下，读出仍然有效、并且有证据支撑的答案。",
        31 * mm,
        145 * mm,
        PAGE_W - 62 * mm,
        28 * mm,
    )

    y, h, gap = 91 * mm, 26 * mm, 6 * mm
    labels = [("可见记忆", "对话 / 消息 / 日志"), ("STS Graph", "持续整理记忆"), ("STS", "Scope-Time-State<br/>理解问题约束"), ("有证据的答案", "读出当前状态")]
    x = 31 * mm
    w = (PAGE_W - 62 * mm - 3 * gap) / 4
    for i, (title, sub) in enumerate(labels):
        flow_box(c, x, y, w, h, title, sub)
        if i < len(labels) - 1:
            arrow(c, x + w + 2, x + w + gap - 1, y + h / 2)
        x += w + gap

    draw_para(c, "我们关注的不是某一条最新消息，而是记忆在时间中如何变化，以及什么状态在当前仍然成立。", 31 * mm, 73 * mm, PAGE_W - 62 * mm, 13, 21, MUTED)
    draw_para(c, "当前主线：EverMemBench、LoCoMo-QA 与 EPBench。", 31 * mm, 55 * mm, PAGE_W - 62 * mm, 10.5, 16, MUTED)
    draw_para(c, "2026-07 | EpisodicMemory", 31 * mm, 22 * mm, 100 * mm, 8.5, 12, MUTED)
    footer(c, 1)


def page_two(c: canvas.Canvas) -> None:
    section_title(c, "1", "我们解决的是什么问题", "长期记忆的难点不只是相关内容在哪里，而是它在什么范围、什么时间语义下仍然有效。")
    callout(c, "研究问题：给定一个持续展开的长期记忆源和一个问题，如何构造目标范围内、当前有效、由证据支撑的状态答案？", 31 * mm, 210 * mm, PAGE_W - 62 * mm, 26 * mm)
    rows = [
        ("维度", "我们要回答的问题"),
        ("Scope", "问题指向哪个人物、项目、主题、会话或情节对象？"),
        ("Time", "问题问的是已经发生、正在更新、计划、截止，还是当前状态？"),
        ("State", "面对修改、替代、冲突和复述，什么内容现在仍然成立？"),
    ]
    simple_table(c, 31 * mm, 195 * mm, [34 * mm, PAGE_W - 62 * mm - 34 * mm], rows, 16 * mm, font_size=10.8)
    draw_para(c, "因此，答案不能只依赖“最相似”或“最新”的文本。它需要同时解释：问的是谁，时间语义是什么，以及哪些历史状态已经被更新。", 31 * mm, 105 * mm, PAGE_W - 62 * mm, 13, 22, TEXT)
    callout(c, "STS 的核心视角：Scope 确定范围，Time 解释变化，State 判断有效性。三者共同决定应该读出哪一部分记忆。", 31 * mm, 58 * mm, PAGE_W - 62 * mm, 24 * mm, fill=colors.HexColor("#F1F6FA"))
    footer(c, 2)


def page_three(c: canvas.Canvas) -> None:
    section_title(c, "2", "Solution：构图阶段的状态图", "我们先把记忆中的事件、范围、时间和状态整理好，再让问题去读取它。")
    y, h, gap = 178 * mm, 27 * mm, 3.5 * mm
    labels = [
        ("记忆流", "对话 / 日志"),
        ("Events", "来源 / 顺序"),
        ("Scope", "人 / 项目 / 主题"),
        ("Claim + Time", "事实 / 时间"),
        ("State", "状态 / 更新"),
        ("持久化图", "可重复读取"),
    ]
    x = 31 * mm
    w = (PAGE_W - 62 * mm - 5 * gap) / 6
    for i, (title, sub) in enumerate(labels):
        flow_box(c, x, y, w, h, title, sub)
        if i < len(labels) - 1:
            arrow(c, x + w + 1, x + w + gap - 1, y + h / 2)
        x += w + gap

    bullet_list(
        c,
        [
            "Event 保留原始记忆的来源、顺序和时间锚点，让后续答案能够回到具体证据。",
            "Scope 把人物、项目、主题、群组或会话等范围对象显式整理出来，并把相关 Event 与 Claim 连接到对应范围。一个事件可以同时属于多个范围。",
            "Claim + Time 把记忆中的决定、状态、计划、风险、偏好和下一步整理成带有时间语义的状态信息。",
            "Time 不只是日期标签，它说明一条信息是发生、更新、计划、截止、开始、完成，还是从某个时刻起有效。",
            "State 把同一范围中的状态变化组织起来，区分仍然有效的内容与已经被修正、替代或冲突的内容。",
        ],
        31 * mm,
        146 * mm,
        PAGE_W - 62 * mm,
        size=10.8,
        leading=17,
        gap=5,
    )
    callout(c, "数据边界：图只从 benchmark-visible 的原始记忆源构建，不把 QA、答案、gold evidence 或题型标签写入记忆图。", 31 * mm, 45 * mm, PAGE_W - 62 * mm, 23 * mm)
    draw_para(c, "目的：让“范围”和“状态变化”可以被保存、检查和追溯。", 31 * mm, 41 * mm, PAGE_W - 62 * mm, 10.5, 16, MUTED)
    footer(c, 3)


def page_four(c: canvas.Canvas) -> None:
    section_title(c, "3", "查询阶段：先定位范围，再检索有效证据", "查询时，问题不是简单地寻找相似文本，而是先确定 Scope，再在范围内读取经过 Time 和 State 约束的证据。")
    y, h, gap = 180 * mm, 26 * mm, 6 * mm
    labels = [("Question", "问题"), ("Scope", "定位相关范围"), ("Retrieval", "范围内检索证据"), ("Time + State", "时间 / 状态"), ("Answer", "有证据支撑")]
    x = 31 * mm
    w = (PAGE_W - 62 * mm - 4 * gap) / 5
    for i, (title, sub) in enumerate(labels):
        flow_box(c, x, y, w, h, title, sub)
        if i < len(labels) - 1:
            arrow(c, x + w + 2, x + w + gap - 1, y + h / 2)
        x += w + gap

    rows = [
        ("Scope", "先确认问题所指的对象和范围，避免把相似但无关的记忆混在一起。"),
        ("Retrieval", "在已经确定的范围内寻找相关 Event、Claim 和 State，形成回答所需的候选证据。"),
        ("Time", "识别问题是在问发生过什么、接下来计划什么，还是当前仍然有效的状态。"),
        ("State", "结合状态变化判断哪些信息被更新、替代或否定，避免把旧结论当成当前答案。"),
        ("Evidence", "答案回到图中的事件和状态依据，保持可解释、可追溯。"),
    ]
    simple_table(c, 31 * mm, 143 * mm, [31 * mm, PAGE_W - 62 * mm - 31 * mm], [("读取维度", "查询时的作用"), *rows], 13 * mm, font_size=9.8)
    callout(c, "查询的核心：Scope 决定去哪里找，Retrieval 找到相关证据，Time 和 State 决定哪些证据真正能回答当前问题。", 31 * mm, 37 * mm, PAGE_W - 62 * mm, 23 * mm, fill=colors.HexColor("#F1F6FA"))
    footer(c, 4)


def page_five(c: canvas.Canvas) -> None:
    section_title(c, "4", "当前验证范围与 Solution 主张", "不同 benchmark 使用各自的输入和评测边界，但都围绕 Scope、Time、State 的核心问题展开。")
    rows = [
        ("验证载体", "在 Solution 中承担的角色"),
        ("EverMemBench", "当前主线：主题级对话记忆，验证长期状态的整理与读取。"),
        ("LoCoMo-QA", "当前主线：sample 级对话记忆，验证多跳、时间和开放域问题中的状态读取。"),
        ("EPBench", "当前主线：叙事记忆验证，检验跨段落、章节和长事件流中的 episodic 状态理解。"),
    ]
    simple_table(c, 31 * mm, 205 * mm, [42 * mm, PAGE_W - 62 * mm - 42 * mm], rows, 17 * mm, font_size=10.2)
    callout(c, "Solution 主张：当一个问题同时依赖范围判断、时间语义和状态有效性时，持久化的 Scope-Time-State Graph 能够把分散、变化中的记忆组织成更清晰、更可追溯的证据链。", 31 * mm, 103 * mm, PAGE_W - 62 * mm, 27 * mm)
    draw_para(c, "一句话总结：Scope 定范围，Time 解释变化，State 判断有效性，Evidence 让答案回到原始记忆和状态依据。", 31 * mm, 89 * mm, PAGE_W - 62 * mm, 11.5, 18, NAVY)
    footer(c, 5)


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUT), pagesize=A4)
    c.setTitle("Scope-Time-State Memory Graph | Solution")
    page_one(c)
    c.showPage()
    page_two(c)
    c.showPage()
    page_three(c)
    c.showPage()
    page_four(c)
    c.showPage()
    page_five(c)
    c.save()


if __name__ == "__main__":
    build()
