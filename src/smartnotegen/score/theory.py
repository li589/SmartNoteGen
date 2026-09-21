"""乐理辅助：调号、音名拼写、时值分解（纯函数，无第三方依赖）。

为什么单独一层
--------------
谱面渲染里最容易出错的不是画线，而是「这个音该写成 C# 还是 Db、要不要画升号」。
把这类判断收敛成纯函数，渲染层（SVG / 简谱 / PNG / MusicXML）才能共用同一套结论，
测试也才能脱离像素直接断言。

三组能力
--------
1. 调号：``normalize_key`` / ``key_fifths`` / ``key_accidentals`` —— 五度圈查表，不依赖 music21。
2. 拼写：``spell_pitch`` —— 按调号升降偏好把 MIDI pitch 落到「字母 + 变音记号 + 音级序号」。
3. 时值：``duration_components`` —— 把任意拍数贪心分解为可记谱的（音符类型, 附点数）序列。

时间单位约定：本模块中的「拍」一律指**四分音符**，与 ``models/notes.py`` 一致。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 基础常量
# ---------------------------------------------------------------------------

#: 音级字母序号：0=C 1=D 2=E 3=F 4=G 5=A 6=B
LETTERS = "CDEFGAB"

#: 升号出现顺序（五度圈向右）
_SHARP_ORDER = "FCGDAEB"
#: 降号出现顺序（五度圈向左）
_FLAT_ORDER = "BEADGCF"

#: 音高类 -> (字母序号, 变音记号)，升号偏好
_SHARP_SPELLING: Dict[int, Tuple[int, int]] = {
    0: (0, 0),    # C
    1: (0, 1),    # C#
    2: (1, 0),    # D
    3: (1, 1),    # D#
    4: (2, 0),    # E
    5: (3, 0),    # F
    6: (3, 1),    # F#
    7: (4, 0),    # G
    8: (4, 1),    # G#
    9: (5, 0),    # A
    10: (5, 1),   # A#
    11: (6, 0),   # B
}

#: 音高类 -> (字母序号, 变音记号)，降号偏好
_FLAT_SPELLING: Dict[int, Tuple[int, int]] = {
    0: (0, 0),    # C
    1: (1, -1),   # Db
    2: (1, 0),    # D
    3: (2, -1),   # Eb
    4: (2, 0),    # E
    5: (3, 0),    # F
    6: (4, -1),   # Gb
    7: (4, 0),    # G
    8: (5, -1),   # Ab
    9: (5, 0),    # A
    10: (6, -1),  # Bb
    11: (6, 0),   # B
}

#: 五度圈：大调主音（如 "C" / "F#" / "Bb"）-> 升降号数
_MAJOR_FIFTHS: Dict[str, int] = {
    "C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "C#": 7,
    "F": -1, "Bb": -2, "Eb": -3, "Ab": -4, "Db": -5, "Gb": -6, "Cb": -7,
}

#: 五度圈：小调主音 -> 升降号数
_MINOR_FIFTHS: Dict[str, int] = {
    "A": 0, "E": 1, "B": 2, "F#": 3, "C#": 4, "G#": 5, "D#": 6, "A#": 7,
    "D": -1, "G": -2, "C": -3, "F": -4, "Bb": -5, "Eb": -6, "Ab": -7,
}


# ---------------------------------------------------------------------------
# 调号
# ---------------------------------------------------------------------------

def normalize_key(key: str) -> Tuple[str, str]:
    """把任意写法的调式归一化为 ``(主音, 调式)``。

    支持：``"C major"`` / ``"c"`` / ``"Am"`` / ``"a minor"`` / ``"F#小调"`` / ``"Bb"``。

    Args:
        key: 原始调式字符串。

    Returns:
        ``(tonic, mode)``，tonic 形如 ``"C"`` / ``"F#"`` / ``"Bb"``，mode 为 ``"major"`` 或 ``"minor"``。

    Raises:
        ValueError: 无法解析或主音不在五度圈表内。
    """
    raw = (key or "").strip()
    if not raw:
        return "C", "major"

    text = raw.replace("大调", " major").replace("小调", " minor")

    if " " in text:
        parts = text.split()
        tonic_part = parts[0]
        tail = " ".join(parts[1:]).lower()
        # "B flat major" 这种写法把变音记号与主音分开，先折回主音
        if tail in ("flat", "sharp") or tail.startswith(("flat ", "sharp ")):
            mark = "b" if tail.startswith("flat") else "#"
            tonic_part += mark
            tail = tail[len("flat") if mark == "b" else len("sharp"):].strip()
        mode = _parse_mode_word(tail, original=raw)
    else:
        # 无空格：形如 "Am" / "C" / "F#" / "Bbm" / "Cmin"
        body = text.strip()
        low = body.lower()
        mode = "major"
        for suffix in ("minor", "min", "moll"):
            if low.endswith(suffix) and len(body) > len(suffix):
                mode = "minor"
                body = body[: -len(suffix)]
                break
        else:
            if low.endswith("maj") and len(body) > 3:
                body = body[:-3]
            elif low.endswith("m") and len(body) > 1:
                mode = "minor"
                body = body[:-1]
        tonic_part = body

    tonic = _canonical_tonic(tonic_part)
    table = _MAJOR_FIFTHS if mode == "major" else _MINOR_FIFTHS
    if tonic not in table:
        raise ValueError(f"无法识别的调式主音: {key!r}（解析为 {tonic!r}）")
    return tonic, mode


#: 允许的调式词（空格写法用）
_MAJOR_WORDS = frozenset({"major", "maj", "ionian"})
_MINOR_WORDS = frozenset({"minor", "min", "moll", "aeolian", "m"})


def _parse_mode_word(tail: str, *, original: str) -> str:
    """解析空格写法里的调式词；无法识别即报错（不静默当大调）。"""
    word = (tail or "").strip().lower()
    if not word or word in _MAJOR_WORDS:
        return "major"
    if word in _MINOR_WORDS:
        return "minor"
    raise ValueError(f"无法识别的调式写法: {original!r}（调式词 {tail!r} 不认识）")


def _canonical_tonic(text: str) -> str:
    """``"c#"`` -> ``"C#"``；``"bb"`` -> ``"Bb"``。

    变音记号只接受单个升/降号（``"#"`` / ``"b"`` / ``"sharp"`` / ``"flat"``）；
    ``"C##"``、``"Cb#"`` 之类重升重降一律报错，避免拼写层出现表外音名。
    """
    body = (text or "").strip()
    if not body:
        return "C"
    letter = body[0].upper()
    if letter not in LETTERS:
        raise ValueError(f"非法音名: {text!r}")
    rest = body[1:].strip().lower()
    if rest in ("", "natural", "nature", "n"):
        mark = ""
    elif rest in ("#", "sharp", "s"):
        mark = "#"
    elif rest in ("b", "flat", "f"):
        mark = "b"
    else:
        raise ValueError(f"非法变音记号: {text!r}")
    return f"{letter}{mark}"


def key_fifths(key: str) -> int:
    """返回调号的升降号数（正=升号个数，负=降号个数，0=无升降）。"""
    tonic, mode = normalize_key(key)
    table = _MAJOR_FIFTHS if mode == "major" else _MINOR_FIFTHS
    return table[tonic]


def prefer_flats(key: str) -> bool:
    """该调是否应优先用降号拼写（五度圈左侧调）。"""
    return key_fifths(key) < 0


def relative_major(minor_tonic: str) -> str:
    """小调主音 -> 关系大调主音。

    简谱记小调时用**关系大调**作 ``1``，小调主音记作 ``6``（la 为主音的记法），
    故 ``"A"`` -> ``"C"``、``"D"`` -> ``"F"``、``"Bb"`` -> ``"Db"``。
    两调调号相同，因此直接用五度圈反查，不另存一张表。

    Raises:
        ValueError: 主音不在小调五度圈表内。
    """
    tonic = _canonical_tonic(minor_tonic)
    fifths = _MINOR_FIFTHS.get(tonic)
    if fifths is None:
        raise ValueError(f"无法识别的小调主音: {minor_tonic!r}")
    for name, value in _MAJOR_FIFTHS.items():
        if value == fifths:
            return name
    raise ValueError(f"无对应关系大调: {minor_tonic!r}")  # pragma: no cover - 两表同域


def key_accidentals(fifths: int) -> Dict[int, int]:
    """调号 -> ``{字母序号: 变音记号}``。

    Args:
        fifths: 升降号数。

    Returns:
        如 ``1`` -> ``{3: 1}``（F#）；``-3`` -> ``{6: -1, 2: -1, 5: -1}``（Bb Eb Ab）。
    """
    result: Dict[int, int] = {}
    if fifths > 0:
        for i in range(min(fifths, 7)):
            result[LETTERS.index(_SHARP_ORDER[i])] = 1
    elif fifths < 0:
        for i in range(min(-fifths, 7)):
            result[LETTERS.index(_FLAT_ORDER[i])] = -1
    return result


# ---------------------------------------------------------------------------
# 音名拼写
# ---------------------------------------------------------------------------

#: 音高类 -> 字母序号（不带变音记号）
PITCH_LETTER: Tuple[int, ...] = (0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6)


def diatonic_number(pitch: int) -> int:
    """MIDI pitch -> 音级序号（C0 为 0，相邻音级差 1）。

    口径：``C0``（MIDI 12）= 0，故 ``C4``（MIDI 60）= 28；MIDI 0（``C-1``）为 -7。
    只关心「第几个音级」而不关心升降记号的场景（谱号判定、加线范围）用它，
    比 ``spell_pitch`` 便宜且不需要指定拼写偏好。
    """
    return (pitch // 12 - 1) * 7 + PITCH_LETTER[pitch % 12]


def spell_pitch(pitch: int, flats: bool = False) -> Tuple[int, int, int]:
    """把 MIDI pitch 拼写为 ``(字母序号, 音级序号, 变音记号)``。

    音级序号（diatonic number）以 C0（MIDI 12）为 0，相邻音级差 1，用于换算五线谱位置：
    线间距恰好等于 2 个音级。

    Args:
        pitch: MIDI 音高 0-127。
        flats: True 时优先用降号拼写（如 Db 而非 C#）。

    Returns:
        ``(letter_index, diatonic_number, accidental)``，accidental ∈ {-1, 0, 1}。
    """
    table = _FLAT_SPELLING if flats else _SHARP_SPELLING
    letter, accidental = table[pitch % 12]
    octave = pitch // 12 - 1
    return letter, octave * 7 + letter, accidental


def spelling_name(pitch: int, flats: bool = False) -> str:
    """``60`` -> ``"C4"``；``61`` 且 flats=True -> ``"Db4"``。"""
    letter, diatonic, accidental = spell_pitch(pitch, flats)
    mark = {-1: "b", 0: "", 1: "#"}[accidental]
    # 音级序号 // 7 即八度（C 起算；负数向下取整恰好正确）
    return f"{LETTERS[letter]}{mark}{diatonic // 7}"


def accidental_glyph(
    letter: int, note_accidental: int, key_acc: Dict[int, int]
) -> Optional[int]:
    """决定该音是否需要画变音记号，以及画什么。

    Args:
        letter: 字母序号 0-6。
        note_accidental: 该音实际变音记号（-1/0/1）。
        key_acc: ``key_accidentals()`` 的结果。

    Returns:
        ``None`` 表示调号已覆盖、无需绘制；``0`` 表示需画还原号；
        ``±1`` 表示需画升/降号。
    """
    key_value = key_acc.get(letter, 0)
    if key_value == note_accidental:
        return None
    return note_accidental


# ---------------------------------------------------------------------------
# 时值
# ---------------------------------------------------------------------------

#: (音符类型, 附点数, 四分音符数, 符尾数)；按值降序供贪心分解
DURATION_TABLE: List[Tuple[str, int, float, int]] = [
    ("whole", 1, 6.0, 0),
    ("whole", 0, 4.0, 0),
    ("half", 1, 3.0, 0),
    ("half", 0, 2.0, 0),
    ("quarter", 1, 1.5, 0),
    ("quarter", 0, 1.0, 0),
    ("eighth", 1, 0.75, 1),
    ("eighth", 0, 0.5, 1),
    ("16th", 1, 0.375, 2),
    ("16th", 0, 0.25, 2),
    ("32nd", 1, 0.1875, 3),
    ("32nd", 0, 0.125, 3),
    ("64th", 1, 0.09375, 4),
    ("64th", 0, 0.0625, 4),
]

#: 音符类型 -> 符尾/符杠数
BEAMS: Dict[str, int] = {name: beams for name, _dots, _value, beams in DURATION_TABLE}

#: 音符类型 -> 是否有符头为空心（全音符/二分音符）
OPEN_HEAD = {"whole", "half"}

DURATION_EPS = 1e-6


def duration_components(quarters: float) -> List[Tuple[str, int, float]]:
    """把任意时值（四分音符数）分解为可记谱片段序列（相邻片段需用延音线相连）。

    例：``5.0`` -> ``[("whole",0,4.0), ("quarter",0,1.0)]``；
    ``3.0`` -> ``[("half",1,3.0)]``。

    **契约：分解结果之和恒 ≤ 输入**（宁可少记、不可多记）。理由是三处消费方都会被
    「多记」伤到：排版层会把片段当作事件铺开（末片越界会盖住后一个音）、简谱层会多画
    一条延音横线（小节内记号数超出容量）、补休止符会算出比空隙更长的休止符（与后音
    重叠）。少记的部分（不足 1/64 拍）本就无法记谱，丢弃是唯一诚实的处理。

    唯一例外：输入本身短于最短可记谱时值（1/64 拍）时，返回**单个 64 分音符**——
    否则极短音会在谱面上凭空消失（``model`` 只过滤 ≤1e-6 拍的音，其余会走到这里）。

    Args:
        quarters: 时值，单位为四分音符。

    Returns:
        ``[(音符类型, 附点数, 实际四分音符值), ...]``；输入非正时返回空列表。
    """
    remaining = float(quarters)
    if remaining <= DURATION_EPS:
        return []
    out: List[Tuple[str, int, float]] = []
    for name, dots, value, _beams in DURATION_TABLE:
        while remaining >= value - DURATION_EPS:
            out.append((name, dots, value))
            remaining -= value
            if remaining <= DURATION_EPS:
                break
    if not out:
        # 输入短于 1/64 拍：无法精确记谱，取最短时值保证「音不丢」
        out.append(("64th", 0, 0.0625))
    return out


def note_beams(note_type: str) -> int:
    """音符类型 -> 符尾数（≥1 才可能成组连杠）。"""
    return BEAMS.get(note_type, 0)


# ---------------------------------------------------------------------------
# 拍号
# ---------------------------------------------------------------------------

def parse_time_signature(ts: str) -> Tuple[int, int]:
    """``"4/4"`` -> ``(4, 4)``。

    Raises:
        ValueError: 格式非法或分子/分母非正。
    """
    try:
        num_s, den_s = str(ts).split("/")
        num, den = int(num_s), int(den_s)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"非法拍号: {ts!r}（期望形如 '4/4'）") from exc
    if num <= 0 or den <= 0:
        raise ValueError(f"非法拍号: {ts!r}（分子分母须为正）")
    return num, den


def beats_per_measure(ts: str) -> float:
    """小节容量（单位：四分音符）。``"4/4"`` -> 4.0；``"6/8"`` -> 3.0。"""
    num, den = parse_time_signature(ts)
    return num * 4.0 / den


def beat_unit(ts: str) -> float:
    """拍号的分母对应的四分音符时值（用于简谱下划线分组）。``"6/8"`` -> 0.5。"""
    _num, den = parse_time_signature(ts)
    return 4.0 / den
