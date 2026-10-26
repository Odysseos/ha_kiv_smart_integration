# SPDX-License-Identifier: GPL-3.0-only
"""Launch the standalone settings page and its embedded loopback server."""
import argparse
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description="Локальные настройки VAKIO KIV Smart")
    parser.add_argument("html", nargs="?", type=Path,
                        default=Path(__file__).with_suffix(".html"),
                        help="Путь к vakio_settings.html (по умолчанию рядом с программой)")
    source = parser.parse_args().html.resolve()
    try:
        html = source.read_text(encoding="utf-8")
        code = html.split("<!-- LOCAL_SERVER_BEGIN\n", 1)[1].split("\nLOCAL_SERVER_END -->", 1)[0]
    except (OSError, IndexError) as error:
        parser.exit(1, f"Не удалось прочитать локальный сервер из {source}: {error}\n")
    sys.argv = [str(Path(__file__).resolve()), str(source)]
    exec(compile(code, str(source), "exec"), {"__name__": "__main__"})


if __name__ == "__main__":
    main()
