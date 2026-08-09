"""和弦转位（P2-2c）：根据旋律音/声部流畅性自动选择转位。

目标：低音声部相邻音程差最小化（更平滑），同时保持和弦功能（音级集合不变，
根音位置仍正确）。仅作用于和弦轨（chords），默认关闭。
"""

from __future__ import annotations

from typing import List, Optional

from smartnotegen.models.notes import Note, NoteSequence


def _beats_per_bar(time_signature: str) -> float:
    try:
        num, den = time_signature.split("/")
        return float(num) * 4.0 / float(den)
    except (ValueError, AttributeError):
        return 4.0


class InversionResolver:
    """和弦转位解析器：逐小节选择使低音最平滑的转位 voicing。"""

    #: 低音搜索区间（C2 ~ C5）
    BASS_LOW = 36
    BASS_HIGH = 72

    def resolve(
        self,
        seq: NoteSequence,
        smoothness_weight: float = 1.0,
    ) -> NoteSequence:
        """解析转位并重写和弦轨。

        Args:
            seq: 输入 NoteSequence（就地修改 chords 轨）。
            smoothness_weight: 平滑权重（越大越偏好低音移动最小；当前恒为正则项）。

        Returns:
            处理后的 NoteSequence（与输入同一实例）。
        """
        chords_track = next((t for t in seq.tracks if t.name == "chords"), None)
        if chords_track is None or not chords_track.notes:
            return seq
        beats_per_bar = _beats_per_bar(seq.time_signature)
        bars = max(1, seq.bars)

        new_notes: List[Note] = []
        prev_bass: Optional[int] = None
        for bar in range(bars):
            bar_start = bar * beats_per_bar
            bar_notes = [
                n for n in chords_track.notes
                if bar_start <= n.start < bar_start + beats_per_bar
            ]
            if not bar_notes:
                continue
            pcs = sorted({n.pitch % 12 for n in bar_notes})
            if not pcs:
                continue
            best_bass, best_voicing = self._pick_voicing(pcs, prev_bass, smoothness_weight)
            prev_bass = best_bass
            duration = max(n.duration for n in bar_notes)
            velocity = bar_notes[0].velocity
            start = bar_notes[0].start
            for v in best_voicing:
                new_notes.append(Note(pitch=v, start=start, duration=duration, velocity=velocity))

        chords_track.notes = new_notes
        return seq

    def _pick_voicing(
        self,
        pcs: List[int],
        prev_bass: Optional[int],
        smoothness_weight: float,
    ) -> tuple[int, List[int]]:
        """选择转位：以每个和弦音级作为低音候选，构造向上堆叠的 voicing。

        返回 (低音 pitch, voicing 音高列表)。
        """
        ordered = sorted(pcs)
        anchor = prev_bass if prev_bass is not None else 48
        best: Optional[tuple[float, int, List[int]]] = None
        for idx, pc in enumerate(ordered):
            bass_candidates = [
                p for p in range(self.BASS_LOW, self.BASS_HIGH + 1) if p % 12 == pc
            ]
            if not bass_candidates:
                continue
            bass = min(bass_candidates, key=lambda p: abs(p - anchor))
            voicing = [bass]
            cur = bass
            for k in range(1, len(ordered)):
                target_pc = ordered[(idx + k) % len(ordered)]
                step = (target_pc - cur) % 12
                if step == 0:
                    step = 12
                cur = cur + step
                voicing.append(cur)
            cost = abs(bass - anchor) * float(smoothness_weight)
            if best is None or cost < best[0]:
                best = (cost, bass, voicing)
        assert best is not None
        return best[1], best[2]
