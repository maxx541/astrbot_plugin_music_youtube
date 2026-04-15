"""Utility functions"""

from enum import IntEnum


class SendMode(IntEnum):
    """Song sending mode constants"""

    CARD = 1
    RECORD = 2
    FILE = 3
    TEXT = 4


# Text mode mapping (Chinese and English)
MODE_MAP_CN: dict[str, SendMode] = {
    "卡片": SendMode.CARD,
    "语音": SendMode.RECORD,
    "文件": SendMode.FILE,
    "文本": SendMode.TEXT,
    "card": SendMode.CARD,
    "record": SendMode.RECORD,
    "file": SendMode.FILE,
    "text": SendMode.TEXT,
}


def parse_user_input(arg: str) -> tuple[int, list[str] | None, str | None]:
    """
    Parse user song selection input format.

    Supported formats:
        - "2"        → Select 2nd song, default mode
        - "1 2"      → Select 1st song, mode 2 (voice)
        - "1 卡片"   → Select 1st song, card mode
        - "1 record" → Select 1st song, voice mode

    Returns:
        (index, modes, error):
            - index: Song index (0 = parse failed)
            - modes: Send modes list (None = use default)
            - error: Error message (None = no error)
    """
    parts = arg.split()
    index = 0
    way = None
    modes = None
    mode_map = {
        SendMode.CARD: ["card"],
        SendMode.RECORD: ["record"],
        SendMode.FILE: ["file"],
        SendMode.TEXT: ["text"],
    }

    # Case 1: Single number "2"
    if len(parts) == 1 and parts[0].isdigit():
        index = int(parts[0])

    # Case 2: "number mode" format "1 2" (number number)
    elif len(parts) == 2 and parts[0].isdigit():
        index = int(parts[0])
        second_part = parts[1]

        # Try to parse as number
        if second_part.isdigit():
            mode_value = int(second_part)
            if 1 <= mode_value <= 4:
                way = SendMode(mode_value)
            else:
                return (
                    0,
                    None,
                    "Mode should be 1-4: 1-card 2-voice 3-file 4-text"
                )
        else:
            # Try to match text mode
            way = MODE_MAP_CN.get(second_part)
            if way is None:
                return (
                    0,
                    None,
                    f"Unknown mode「{second_part}」, "
                    "available: card/voice/file/text or 1/2/3/4"
                )
    modes = mode_map.get(way) if way else None
    return index, modes, None
