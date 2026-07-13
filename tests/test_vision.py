"""vision 서비스 단위 테스트: 다운샘플·phash 유사 매칭·캐시 분기."""

from __future__ import annotations

import io
from unittest.mock import MagicMock

from PIL import Image

from src.services.vision import VisionService, _nearest_phash, _prepare


def _img_bytes(size: tuple[int, int] = (64, 64), color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


# --- _prepare (2a 다운샘플) ---------------------------------------------------


def test_prepare_downsamples_large_image() -> None:
    send, media, phash = _prepare(_img_bytes(size=(2000, 1200)))
    assert media == "image/jpeg"
    assert phash is not None
    out = Image.open(io.BytesIO(send))
    assert max(out.size) <= 1024


def test_prepare_keeps_small_image() -> None:
    raw = _img_bytes(size=(300, 200))
    send, media, phash = _prepare(raw)
    assert send == raw  # 원본 그대로 전송
    assert media == "image/png"
    assert phash is not None


def test_prepare_bad_bytes_graceful() -> None:
    send, media, phash = _prepare(b"not an image at all")
    assert send == b"not an image at all"
    assert phash is None


# --- _nearest_phash (2b 매칭 로직) --------------------------------------------


def test_nearest_phash_within_distance() -> None:
    target = "0000000000000000"
    cands = [("0000000000000003", "가까운 차트"), ("ffffffffffffffff", "다른 차트")]
    assert _nearest_phash(target, cands, max_distance=4) == ("가까운 차트", 2)


def test_nearest_phash_over_distance_returns_none() -> None:
    target = "0000000000000000"
    assert _nearest_phash(target, [("ffffffffffffffff", "다른 차트")], max_distance=4) is None


# --- describe 캐시 분기 --------------------------------------------------------


def test_describe_exact_cache_hit_skips_api() -> None:
    state = MagicMock()
    state.get_image_cache.return_value = "캐시된 설명"
    client = MagicMock()
    vs = VisionService(client, "haiku", state)
    assert vs.describe("sha", b"x") == "캐시된 설명"
    client.messages.create.assert_not_called()


def test_describe_phash_enabled_reuses_and_skips_api() -> None:
    img = _img_bytes()
    _, _, phash = _prepare(img)
    assert phash is not None
    state = MagicMock()
    state.get_image_cache.return_value = None
    state.get_image_phashes.return_value = [(phash, "이전 차트 설명")]
    client = MagicMock()
    vs = VisionService(client, "haiku", state, enable_phash_cache=True, phash_max_distance=4)
    out = vs.describe("sha_new", img)
    assert out == "이전 차트 설명"
    client.messages.create.assert_not_called()
    state.set_image_cache.assert_called_once()  # 새 sha1→설명으로 exact 캐시 워밍


def test_describe_phash_shadow_still_calls_api() -> None:
    img = _img_bytes()
    _, _, phash = _prepare(img)
    assert phash is not None
    state = MagicMock()
    state.get_image_cache.return_value = None
    state.get_image_phashes.return_value = [(phash, "이전 차트 설명")]
    client = MagicMock()
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "새 설명"
    client.messages.create.return_value = MagicMock(content=[text_block])
    vs = VisionService(client, "haiku", state, enable_phash_cache=False, phash_max_distance=4)
    out = vs.describe("sha_new", img)
    assert out == "새 설명"
    client.messages.create.assert_called_once()
