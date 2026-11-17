import json
import sys
import traceback
from pathlib import Path

from brisim_tl506 import TL506Downloader


def emit(event, **details):
    print(
        json.dumps(
            {"event": event, **details},
            ensure_ascii=False,
        ),
        flush=True,
    )


def main():
    downloader = TL506Downloader()
    error_details = None

    try:
        request = json.loads(sys.stdin.readline())
        output_dir = Path(request["output_dir"])

        downloader.buka(
            status_callback=lambda message: emit(
                "status",
                message=message,
            )
        )
        downloader.proses(
            request["date"],
            request["branches"],
            output_dir=output_dir,
            progress_callback=lambda current, total, branch, message: emit(
                "progress",
                current=current,
                total=total,
                branch=branch,
                message=message,
            ),
            status_callback=lambda message: emit(
                "status",
                message=message,
            ),
        )
    except Exception as error:
        error_details = {
            "error_type": type(error).__name__,
            "message": str(error).strip() or "Tidak ada pesan error.",
            "traceback": traceback.format_exc(),
        }
    finally:
        try:
            downloader.tutup()
        except Exception as error:
            if error_details is None:
                error_details = {
                    "error_type": type(error).__name__,
                    "message": str(error).strip() or "Tidak ada pesan error.",
                    "traceback": traceback.format_exc(),
                }

    if error_details:
        emit("error", **error_details)
        return 1

    emit("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
