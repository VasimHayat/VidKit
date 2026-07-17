"""Unit tests for clean-command construction and residual-tag verification."""

from __future__ import annotations

from pathlib import Path

from vidkit.core.cleaner import build_clean_command, find_residual_tags
from vidkit.models import MediaInfo, StreamInfo


def media(
    format_tags: dict[str, str] | None = None,
    stream_tags: dict[str, str] | None = None,
    chapters: int = 0,
) -> MediaInfo:
    return MediaInfo(
        path=Path("x.mp4"),
        format_name="mov,mp4",
        duration=30.0,
        size_bytes=1000,
        streams=(
            StreamInfo(index=0, codec_type="video", codec_name="h264", tags=stream_tags or {}),
        ),
        format_tags=format_tags or {},
        chapter_count=chapters,
    )


class TestBuildCleanCommand:
    def test_exact_flags(self) -> None:
        argv = build_clean_command(Path("in.mp4"), Path("out.mp4"))
        joined = " ".join(argv)
        assert "-map 0" in joined
        assert "-map_metadata -1" in joined
        assert "-map_chapters -1" in joined
        assert "-c copy" in joined
        assert "-fflags +bitexact" in joined
        assert "-flags:v +bitexact" in joined
        assert "-flags:a +bitexact" in joined
        assert argv[-1] == "out.mp4"
        assert "-i" in argv
        assert argv[argv.index("-i") + 1] == "in.mp4"

    def test_no_reencode_flags_present(self) -> None:
        argv = build_clean_command(Path("in.mp4"), Path("out.mp4"))
        assert "libx264" not in argv


class TestFindResidualTags:
    def test_clean_file_passes(self) -> None:
        assert find_residual_tags(media()) == []

    def test_structural_defaults_allowed(self) -> None:
        info = media(
            stream_tags={
                "handler_name": "VideoHandler",
                "vendor_id": "[0][0][0][0]",
                "language": "und",
            }
        )
        assert find_residual_tags(info) == []

    def test_format_tags_flagged(self) -> None:
        residual = find_residual_tags(media(format_tags={"title": "secret"}))
        assert len(residual) == 1
        assert "title" in residual[0]

    def test_ftyp_brand_tags_allowed(self) -> None:
        info = media(
            format_tags={
                "major_brand": "isom",
                "minor_version": "512",
                "compatible_brands": "isomiso2avc1mp41",
            }
        )
        assert find_residual_tags(info) == []

    def test_encoder_tag_flagged(self) -> None:
        # bitexact must suppress the encoder tag; if it survives, fail loudly.
        residual = find_residual_tags(media(format_tags={"encoder": "Lavf61"}))
        assert residual

    def test_device_handler_name_flagged(self) -> None:
        residual = find_residual_tags(media(stream_tags={"handler_name": "Core Media Video"}))
        assert residual and "handler_name" in residual[0]

    def test_gps_style_tag_flagged(self) -> None:
        residual = find_residual_tags(media(stream_tags={"location": "+37.77-122.41/"}))
        assert residual

    def test_chapters_flagged(self) -> None:
        residual = find_residual_tags(media(chapters=3))
        assert residual and "chapter" in residual[0]
