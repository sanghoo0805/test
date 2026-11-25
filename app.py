"""간단 계획표 - Streamlit 진입점."""

from __future__ import annotations

import html
from datetime import date, datetime, time, timedelta, timezone
from itertools import groupby

import streamlit as st

import storage

st.set_page_config(page_title="간단 계획표", page_icon="📅", layout="wide")

KST = timezone(timedelta(hours=9))  # 배포 서버(UTC)에서도 한국 기준 "오늘"을 쓰기 위함
WEEKDAYS = "월화수목금토일"
TITLE_MAX = 100
MEMO_MAX = 500
TIME_STEP = 60  # st.time_input 기본값은 15분 간격이므로 1분(60초)으로 지정

DATE_FILTERS = ("전체", "오늘", "특정 날짜")

# 커스텀 스타일은 모두 여기에서 관리한다.
# 글자색은 테마를 따르도록 inherit/opacity만 쓰고, 색을 직접 칠하는 곳은 흰 글씨 배지뿐이다.
CSS = """
<style>
.block-container { max-width: 960px; padding-top: 2.5rem; }
.app-subtitle { opacity: 0.65; margin: -0.75rem 0 1.25rem; }

.day-header {
  display: flex; align-items: center; gap: 0.5rem;
  margin: 1.5rem 0 0.5rem; padding-bottom: 0.35rem;
  border-bottom: 2px solid rgba(128, 128, 128, 0.25);
  font-size: 1.05rem; font-weight: 700;
}
.day-header.is-today { border-bottom-color: #2563eb; }
.day-pill {
  font-size: 0.75rem; font-weight: 600; color: #fff;
  background: #2563eb; border-radius: 999px; padding: 0.1rem 0.55rem;
}
.day-count { margin-left: auto; font-size: 0.8rem; font-weight: 400; opacity: 0.6; }

.ev-time { font-variant-numeric: tabular-nums; line-height: 1.25; }
.ev-time .start { font-size: 1.15rem; font-weight: 700; }
.ev-time .end { font-size: 0.85rem; opacity: 0.65; }

.ev-badge {
  display: inline-block; color: #fff; border-radius: 6px;
  padding: 0.05rem 0.5rem; font-size: 0.78rem; font-weight: 600;
  margin-right: 0.4rem; vertical-align: 0.1em; white-space: nowrap;
}
.ev-title { font-size: 1.02rem; font-weight: 600; overflow-wrap: anywhere; }
.ev-memo {
  margin-top: 0.3rem; font-size: 0.88rem; opacity: 0.75;
  white-space: pre-wrap; overflow-wrap: anywhere;
}

/* 카드의 수정/삭제 버튼: 좁은 폭에서도 한 줄에 나란히 */
[class*="st-key-actions_"] { flex-wrap: nowrap; justify-content: flex-end; }
[class*="st-key-actions_"] button {
  padding: 0.2rem 0.6rem; min-height: 2rem; white-space: nowrap;
}
</style>
"""


# ---------------------------------------------------------------- 공통 유틸

def today() -> date:
    return datetime.now(KST).date()


def to_time(value: str, fallback: time = time(9, 0)) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError):
        return fallback


def to_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return today()


def date_label(d: date) -> str:
    return f"{d.isoformat()} ({WEEKDAYS[d.weekday()]})"


def validate(title: str, start: time, end: time, memo: str) -> list[str]:
    errors = []
    if not title.strip():
        errors.append("제목을 입력해주세요.")
    elif len(title.strip()) > TITLE_MAX:
        errors.append(f"제목은 {TITLE_MAX}자 이하로 입력해주세요.")
    if end <= start:
        errors.append("종료 시간은 시작 시간보다 늦어야 합니다.")
    if len(memo) > MEMO_MAX:
        errors.append(f"메모는 {MEMO_MAX}자 이하로 입력해주세요.")
    return errors


def to_record(title: str, day: date, start: time, end: time, category: str, memo: str) -> dict:
    return {
        "title": title.strip(),
        "date": day.isoformat(),
        "start_time": start.strftime("%H:%M"),
        "end_time": end.strftime("%H:%M"),
        "category": category,
        "memo": memo.strip(),
    }


def flash(message: str, icon: str = "✅") -> None:
    """다음 rerun 후에 보여줄 알림을 남긴다."""
    st.session_state["flash"] = (message, icon)


def category_label(name: str) -> str:
    return f"{storage.CATEGORIES.get(name, '📌')} {name}"


def badge_html(name: str) -> str:
    name = storage.normalize_category(name)
    color = storage.CATEGORY_COLORS[name]
    return f'<span class="ev-badge" style="background:{color}">{html.escape(category_label(name))}</span>'


def sort_key(event: dict) -> tuple[str, str, str]:
    return (event.get("date", ""), event.get("start_time", ""), event.get("end_time", ""))


# ---------------------------------------------------------------- 사이드바

def render_sidebar(events: list[dict]) -> tuple[list[str], str, date | None]:
    """필터 입력과 요약을 그리고, 선택된 필터 값을 반환한다."""
    categories = list(storage.CATEGORIES)
    with st.sidebar:
        st.header("🔍 필터")
        selected = st.multiselect(
            "카테고리",
            categories,
            default=categories,
            format_func=category_label,
            key="filter_categories",
        )
        mode = st.radio("날짜", DATE_FILTERS, horizontal=True, key="filter_date_mode")
        picked = None
        if mode == "특정 날짜":
            picked = st.date_input("날짜 선택", value=today(), key="filter_date")

        st.divider()
        st.header("📊 요약")
        today_str = today().isoformat()
        col1, col2 = st.columns(2)
        col1.metric("전체 일정", f"{len(events)}건")
        col2.metric("오늘 일정", f"{sum(e.get('date') == today_str for e in events)}건")
        counts = {name: 0 for name in categories}  # 카테고리 정의 순서대로 표시
        for e in events:
            counts[storage.normalize_category(e.get("category"))] += 1
        if events:
            st.markdown(
                " ".join(f"{badge_html(n)}<small>{c}</small>&nbsp;" for n, c in counts.items() if c),
                unsafe_allow_html=True,
            )
    return selected, mode, picked


def apply_filters(events: list[dict], categories: list[str], mode: str, picked: date | None) -> list[dict]:
    result = [e for e in events if storage.normalize_category(e.get("category")) in categories]
    if mode == "오늘":
        result = [e for e in result if e.get("date") == today().isoformat()]
    elif mode == "특정 날짜" and picked:
        result = [e for e in result if e.get("date") == picked.isoformat()]
    return result


# ---------------------------------------------------------------- 일정 추가

def render_add_form(has_events: bool) -> None:
    # 추가에 성공하면 버전을 올려 위젯 key를 바꾼다. 새 위젯으로 만들어지므로 입력칸이 비워지고,
    # 유효성 검사에 실패했을 때는 버전이 그대로라 입력값이 유지된다.
    v = st.session_state.setdefault("add_form_version", 0)
    # 일정이 이미 있으면 목록이 먼저 보이도록 접어서 시작한다 (모바일에서 폼이 첫 화면을 덮지 않게).
    with st.expander("➕ 일정 추가", expanded=not has_events):
        with st.form(f"add_form_{v}", border=False):
            c1, c2 = st.columns([3, 1])
            title = c1.text_input("제목 *", max_chars=TITLE_MAX, placeholder="예: 팀 회의", key=f"add_title_{v}")
            category = c2.selectbox(
                "카테고리 *", list(storage.CATEGORIES), format_func=category_label, key=f"add_category_{v}"
            )
            c1, c2, c3 = st.columns(3)
            day = c1.date_input("날짜 *", value=today(), key=f"add_date_{v}")
            start = c2.time_input("시작 시간 *", value=time(9, 0), step=TIME_STEP, key=f"add_start_{v}")
            end = c3.time_input("종료 시간 *", value=time(10, 0), step=TIME_STEP, key=f"add_end_{v}")
            memo = st.text_area(
                "메모", max_chars=MEMO_MAX, height=80, placeholder="장소, 준비물 등 (선택)", key=f"add_memo_{v}"
            )
            submitted = st.form_submit_button("일정 추가", type="primary", icon="➕")

        if submitted:
            errors = validate(title, start, end, memo)
            if errors:
                for msg in errors:
                    st.error(msg, icon="⚠️")
                return
            storage.add_event(to_record(title, day, start, end, category, memo))
            st.session_state["add_form_version"] = v + 1
            flash(f"'{title.strip()}' 일정을 추가했습니다.")
            st.rerun()


# ---------------------------------------------------------------- 일정 수정

@st.dialog("✏️ 일정 수정")
def edit_dialog(event: dict) -> None:
    eid = event["id"]
    categories = list(storage.CATEGORIES)
    current_category = storage.normalize_category(event.get("category"))

    with st.form(f"edit_form_{eid}", border=False):
        title = st.text_input("제목 *", value=event.get("title", ""), max_chars=TITLE_MAX)
        c1, c2 = st.columns(2)
        day = c1.date_input("날짜 *", value=to_date(event.get("date")))
        category = c2.selectbox(
            "카테고리 *",
            categories,
            index=categories.index(current_category),
            format_func=category_label,
        )
        c1, c2 = st.columns(2)
        start = c1.time_input("시작 시간 *", value=to_time(event.get("start_time")), step=TIME_STEP)
        end = c2.time_input(
            "종료 시간 *", value=to_time(event.get("end_time"), time(10, 0)), step=TIME_STEP
        )
        memo = st.text_area("메모", value=event.get("memo", ""), max_chars=MEMO_MAX, height=80)
        c1, c2 = st.columns(2)
        save = c1.form_submit_button("저장", type="primary", width="stretch")
        cancel = c2.form_submit_button("취소", width="stretch")

    if cancel:
        st.rerun()
    if save:
        errors = validate(title, start, end, memo)
        if errors:
            for msg in errors:
                st.error(msg, icon="⚠️")
            return
        if storage.update_event(eid, to_record(title, day, start, end, category, memo)) is None:
            flash("이미 삭제된 일정이라 저장하지 못했습니다.", icon="⚠️")
        else:
            flash(f"'{title.strip()}' 일정을 수정했습니다.")
        st.rerun()


# ---------------------------------------------------------------- 일정 목록

def render_day_header(day: date, count: int) -> None:
    offset = (day - today()).days
    pill = {0: "오늘", 1: "내일"}.get(offset)
    classes = "day-header is-today" if offset == 0 else "day-header"
    pill_html = f'<span class="day-pill">{pill}</span>' if pill else ""
    st.markdown(
        f'<div class="{classes}">{date_label(day)}{pill_html}<span class="day-count">{count}건</span></div>',
        unsafe_allow_html=True,
    )


def render_event(event: dict) -> None:
    eid = event["id"]
    title = html.escape(event.get("title", ""))
    memo = html.escape(event.get("memo", ""))

    with st.container(border=True):
        c_time, c_info, c_actions = st.columns([1, 4.2, 2.2], vertical_alignment="center")
        c_time.markdown(
            f'<div class="ev-time"><div class="start">{html.escape(event.get("start_time", ""))}</div>'
            f'<div class="end">~ {html.escape(event.get("end_time", ""))}</div></div>',
            unsafe_allow_html=True,
        )
        memo_html = f'<div class="ev-memo">{memo}</div>' if memo else ""
        c_info.markdown(
            f'<div>{badge_html(event.get("category", ""))}<span class="ev-title">{title}</span></div>{memo_html}',
            unsafe_allow_html=True,
        )

        # 가로 컨테이너: 모바일에서도 두 버튼이 세로로 쌓이지 않고 나란히 놓인다.
        if st.session_state.get("confirm_delete") == eid:
            c_actions.markdown("**정말 삭제할까요?**")
            buttons = c_actions.container(horizontal=True, gap="small", key=f"actions_confirm_{eid}")
            if buttons.button("삭제", key=f"confirm_yes_{eid}", type="primary"):
                st.session_state.pop("confirm_delete", None)
                storage.delete_event(eid)
                flash(f"'{event.get('title')}' 일정을 삭제했습니다.", icon="🗑️")
                st.rerun()
            if buttons.button("취소", key=f"confirm_no_{eid}"):
                st.session_state.pop("confirm_delete", None)
                st.rerun()
        else:
            buttons = c_actions.container(horizontal=True, gap="small", key=f"actions_{eid}")
            if buttons.button("수정", key=f"edit_{eid}", icon="✏️"):
                # 삭제 확인 상태를 먼저 지우고 다시 그린 뒤 수정 창을 연다 (뒤에 확인 문구가 남지 않게).
                st.session_state.pop("confirm_delete", None)
                st.session_state["edit_target"] = eid
                st.rerun()
            if buttons.button("삭제", key=f"delete_{eid}", icon="🗑️"):
                st.session_state["confirm_delete"] = eid
                st.rerun()


def render_event_list(events: list[dict], total: int) -> None:
    st.subheader("📋 일정 목록")
    if not events:
        st.info("등록된 일정이 없습니다." if total == 0 else "조건에 맞는 일정이 없습니다.", icon="🗓️")
        return
    for day, group in groupby(sorted(events, key=sort_key), key=lambda e: e.get("date", "")):
        group = list(group)
        render_day_header(to_date(day), len(group))
        for event in group:
            render_event(event)


# ---------------------------------------------------------------- main

def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("📅 간단 계획표")
    t = today()
    st.markdown(
        f'<p class="app-subtitle">오늘은 {t.month}월 {t.day}일 ({WEEKDAYS[t.weekday()]})입니다.</p>',
        unsafe_allow_html=True,
    )
    if notice := st.session_state.pop("flash", None):
        message, icon = notice
        st.toast(message, icon=icon)

    events = storage.load_events()
    render_add_form(has_events=bool(events))
    categories, mode, picked = render_sidebar(events)
    render_event_list(apply_filters(events, categories, mode, picked), total=len(events))

    if target := st.session_state.pop("edit_target", None):
        event = next((e for e in events if e["id"] == target), None)
        if event:
            edit_dialog(event)


main()
