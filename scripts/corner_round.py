"""
FontForge 用: 輪郭の「角」を検出して、そこだけ小さな曲線に置き換えることで
グリフの角を少し丸める処理。

考え方:
- グリフは二次ベジエ (TrueType 由来) の輪郭で構成されている前提。
- 各オンカーブ点について、そこに入ってくる方向と出ていく方向のなす角を調べ、
  一定角度以上折れている点だけを「角」とみなす。
- 角と判定した点 P について、P の手前 (radius だけ戻った点 A) と
  P の先 (radius だけ進んだ点 B) を新しいオンカーブ点とし、
  A -> (P を制御点とする二次曲線) -> B に置き換える。
  P 自身をそのまま制御点として使うので、角の "芯" は保ったまま
  少しだけ丸まった自然な曲線になる。
- 角でない点や、それを挟む区間の形状はそのまま維持する。
"""

import math

import fontforge


def round_glyph_corners(glyph, radius, angle_threshold_deg=25):
    """glyph.foreground の角を丸める。失敗した輪郭は元の形状のまま残す。"""
    if radius <= 0:
        return

    layer = glyph.foreground
    new_layer = fontforge.layer()
    new_layer.is_quadratic = layer.is_quadratic

    for contour in layer:
        try:
            rounded = _round_contour(contour, radius, angle_threshold_deg)
        except Exception:
            rounded = None
        new_layer += rounded if rounded is not None else contour

    glyph.foreground = new_layer


def _round_contour(contour, radius, angle_threshold_deg):
    n = len(contour)
    if n < 3 or not contour.closed:
        return None

    pts = [contour[i] for i in range(n)]
    on_indices = [i for i, p in enumerate(pts) if p.on_curve]
    if len(on_indices) < 3:
        return None

    def ref(idx, step):
        return pts[(idx + step) % n]

    # 各オンカーブ点が「角」かどうか、丸める半径込みで判定する
    corners = {}
    for i in on_indices:
        p_in = ref(i, -1)
        p_out = ref(i, 1)
        p = pts[i]
        vin = (p.x - p_in.x, p.y - p_in.y)
        vout = (p_out.x - p.x, p_out.y - p.y)
        len_in = math.hypot(*vin)
        len_out = math.hypot(*vout)
        if len_in < 1e-6 or len_out < 1e-6:
            continue
        ang_in = math.atan2(vin[1], vin[0])
        ang_out = math.atan2(vout[1], vout[0])
        diff = (ang_out - ang_in + math.pi) % (2 * math.pi) - math.pi
        if abs(math.degrees(diff)) >= angle_threshold_deg:
            r = min(radius, len_in * 0.4, len_out * 0.4)
            if r > 0.5:
                corners[i] = r

    if not corners:
        return None

    # 角ごとに、手前に戻った点 A と先に進んだ点 B を求める
    pulled_back = {}
    pushed_fwd = {}
    for i, r in corners.items():
        p = pts[i]
        p_in = ref(i, -1)
        vin = (p.x - p_in.x, p.y - p_in.y)
        din = math.hypot(*vin)
        pulled_back[i] = (p.x - vin[0] / din * r, p.y - vin[1] / din * r)

        p_out = ref(i, 1)
        vout = (p_out.x - p.x, p_out.y - p.y)
        dout = math.hypot(*vout)
        pushed_fwd[i] = (p.x + vout[0] / dout * r, p.y + vout[1] / dout * r)

    def start_point(i):
        return pushed_fwd.get(i, (pts[i].x, pts[i].y))

    def end_point(i):
        return pulled_back.get(i, (pts[i].x, pts[i].y))

    def between(i, j):
        """on_indices 上で i の次から j の手前までの点（制御点があれば1個のはず）"""
        out = []
        k = (i + 1) % n
        while k != j:
            out.append(pts[k])
            k = (k + 1) % n
        return out

    # 新しい輪郭の点列を先に組み立てる（on/off, x, y）。
    # pen プロトコル (moveTo/lineTo/quadraticTo) で構築すると、始点に戻って
    # 閉じる最後の点が「重複したオンカーブ点」として余分に残ってしまい、
    # 結果として長さ0の閉じ辺ができて selfIntersects() が誤検出される問題があった。
    # そのため、元の輪郭と同じ「始点を末尾で繰り返さない」点列を直接組み立てる。
    start_i = on_indices[0]
    waypoints = [(True, start_point(start_i))]

    m = len(on_indices)
    for k in range(m):
        i = on_indices[k]
        nxt = on_indices[(k + 1) % m]
        ctrl_pts = between(i, nxt)

        if len(ctrl_pts) > 1:
            # 想定外（オフカーブが2点以上連続）の場合は丸めを諦めて元形状を使う
            return None
        for c in ctrl_pts:
            waypoints.append((False, (c.x, c.y)))

        waypoints.append((True, end_point(nxt)))
        if nxt in corners:
            p = pts[nxt]
            waypoints.append((False, (p.x, p.y)))
            waypoints.append((True, start_point(nxt)))

    # 末尾が始点と同じオンカーブ点で終わっている場合、それは重複なので取り除く
    # （closed=True にすることで、最後の点から始点への接続は自動的に扱われる）
    if len(waypoints) > 1 and waypoints[-1] == waypoints[0]:
        waypoints.pop()

    nc = fontforge.contour()
    nc.is_quadratic = True
    for on_curve, (x, y) in waypoints:
        nc += fontforge.point(x, y, on_curve)
    nc.closed = True

    return nc
