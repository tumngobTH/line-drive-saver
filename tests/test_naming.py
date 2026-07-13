from app import naming


def test_file_keeps_original_name_with_date_prefix():
    # 2026-07-13 15:30:12 Asia/Bangkok == 1783931412000 ms
    ts = 1783931412000
    assert naming.build_filename("file", ts, original_name="Q2-report.pdf") == "20260713_Q2-report.pdf"


def test_image_uses_date_time_type():
    ts = 1783931412000
    assert naming.build_filename("image", ts) == "20260713_153012_image.jpg"


def test_video_and_audio_extensions():
    ts = 1783931412000
    assert naming.build_filename("video", ts) == "20260713_153012_video.mp4"
    assert naming.build_filename("audio", ts) == "20260713_153012_audio.m4a"


def test_sanitize_strips_path_and_control_chars_but_keeps_thai():
    ts = 1783931412000
    out = naming.build_filename("file", ts, original_name="../ใบเสร็จ\t/x.pdf")
    assert out == "20260713_..ใบเสร็จx.pdf"


def test_resolve_unique_appends_suffix_before_extension():
    existing = {"20260713_a.pdf", "20260713_a_2.pdf"}
    assert naming.resolve_unique("20260713_a.pdf", existing) == "20260713_a_3.pdf"


def test_resolve_unique_returns_name_when_free():
    assert naming.resolve_unique("20260713_a.pdf", set()) == "20260713_a.pdf"
