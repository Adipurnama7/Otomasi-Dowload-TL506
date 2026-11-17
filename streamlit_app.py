import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path

import streamlit as st


# ----------------------------------------------------------------------
# Logika (tidak berubah)
# ----------------------------------------------------------------------
def parse_branch_codes(value):
    branch_codes = [
        line.strip()
        for line in value.splitlines()
        if line.strip()
    ]
    if not branch_codes:
        raise ValueError("Masukkan minimal satu kode branch.")

    invalid = [
        code for code in branch_codes
        if not re.fullmatch(r"\d{1,5}", code)
    ]
    if invalid:
        raise ValueError(
            "Kode branch harus berupa angka 1-5 digit: "
            + ", ".join(invalid)
        )
    normalized_codes = [code.zfill(5) for code in branch_codes]
    if len(set(normalized_codes)) != len(normalized_codes):
        raise ValueError(
            "Daftar branch tidak boleh berisi kode duplikat, "
            "termasuk kode yang sama setelah padding nol."
        )
    return branch_codes


def run_download_worker(
    date_iso,
    branch_codes,
    output_dir,
    status_callback,
    progress_callback,
    log_callback,
):
    worker_path = Path(__file__).with_name("tl506_worker.py")
    creation_flags = (
        subprocess.CREATE_NO_WINDOW
        if os.name == "nt"
        else 0
    )
    worker_error = None
    with subprocess.Popen(
        [sys.executable, "-u", str(worker_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(Path(__file__).resolve().parent),
        creationflags=creation_flags,
    ) as worker:
        if worker.stdin is None or worker.stdout is None:
            raise RuntimeError("Tidak dapat membuka komunikasi dengan worker.")
        request = {
            "date": date_iso,
            "branches": branch_codes,
            "output_dir": str(output_dir),
        }
        worker.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        worker.stdin.close()

        for line in worker.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                log_callback(line)
                continue

            if event.get("event") == "status":
                status_callback(event["message"])
            elif event.get("event") == "progress":
                progress_callback(
                    event["current"],
                    event["total"],
                    event["branch"],
                    event["message"],
                )
            elif event.get("event") == "error":
                worker_error = event

        return_code = worker.wait()

    if worker_error is None and return_code:
        worker_error = {
            "error_type": "WorkerError",
            "message": f"Proses worker berakhir dengan kode {return_code}.",
            "traceback": "",
        }
    return worker_error


# ----------------------------------------------------------------------
# Tampilan
# ----------------------------------------------------------------------
BULAN = [
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]


def format_tanggal(d):
    return f"{d.day} {BULAN[d.month - 1]} {d.year}"


def format_size(num_bytes):
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.2f} MB"


CUSTOM_CSS = """
<style>
    #MainMenu, footer {visibility: hidden;}
    header[data-testid="stHeader"] {background: transparent;}

    .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
        max-width: 1150px;
    }

    :root {
        --brand: #00529C;
        --brand-dark: #003B73;
        --accent: #F58220;
        --border: rgba(128, 128, 128, 0.25);
        --muted: rgba(128, 128, 128, 0.95);
    }

    .app-hero {
        background: linear-gradient(135deg, var(--brand-dark) 0%, var(--brand) 100%);
        border-radius: 16px;
        padding: 28px 32px;
        color: #ffffff;
        margin-bottom: 1.5rem;
        border-bottom: 4px solid var(--accent);
        box-shadow: 0 6px 20px rgba(0, 59, 115, 0.25);
    }
    .app-hero h1 {
        color: #ffffff;
        font-size: 1.9rem;
        font-weight: 700;
        margin: 0 0 6px 0;
        padding: 0;
    }
    .app-hero p {
        color: rgba(255, 255, 255, 0.88);
        margin: 0;
        font-size: 0.97rem;
        line-height: 1.5;
    }
    .app-hero .tag {
        display: inline-block;
        background: rgba(255, 255, 255, 0.16);
        border: 1px solid rgba(255, 255, 255, 0.3);
        border-radius: 999px;
        padding: 2px 12px;
        font-size: 0.75rem;
        letter-spacing: 0.04em;
        margin-bottom: 10px;
    }

    .section-title {
        font-size: 1.05rem;
        font-weight: 600;
        margin: 0 0 2px 0;
    }
    .section-sub {
        font-size: 0.85rem;
        color: var(--muted);
        margin-bottom: 0.75rem;
    }

    .chip-wrap {display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px;}
    .chip {
        background: rgba(0, 82, 156, 0.10);
        color: var(--brand);
        border: 1px solid rgba(0, 82, 156, 0.35);
        border-radius: 8px;
        padding: 2px 10px;
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 0.82rem;
    }
    .chip.more {
        background: transparent;
        border-style: dashed;
        color: var(--muted);
    }

    .step {
        display: flex; gap: 12px; align-items: flex-start;
        margin-bottom: 12px;
    }
    .step .num {
        flex: 0 0 26px; height: 26px;
        border-radius: 50%;
        background: var(--brand);
        color: #fff;
        font-size: 0.8rem; font-weight: 600;
        display: flex; align-items: center; justify-content: center;
    }
    .step .txt {font-size: 0.9rem; line-height: 1.45;}
    .step .txt b {display: block;}
    .step .txt span {color: var(--muted); font-size: 0.84rem;}

    div[data-testid="stMetric"] {
        background: rgba(128, 128, 128, 0.06);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 14px 16px;
    }
    div[data-testid="stMetricLabel"] p {font-size: 0.8rem; color: var(--muted);}

    div[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 14px;}

    .stButton > button, .stDownloadButton > button {
        border-radius: 10px;
        font-weight: 600;
        padding: 0.6rem 1rem;
    }
    .stButton > button[kind="primary"],
    .stDownloadButton > button[kind="primary"] {
        background: var(--brand);
        border: 1px solid var(--brand);
    }
    .stButton > button[kind="primary"]:hover,
    .stDownloadButton > button[kind="primary"]:hover {
        background: var(--brand-dark);
        border-color: var(--brand-dark);
    }

    .footer-note {
        text-align: center;
        color: var(--muted);
        font-size: 0.78rem;
        margin-top: 2rem;
    }
</style>
"""


def render_chips(codes, limit=30):
    shown = "".join(f'<span class="chip">{c.zfill(5)}</span>' for c in codes[:limit])
    if len(codes) > limit:
        shown += f'<span class="chip more">+{len(codes) - limit} lainnya</span>'
    st.markdown(f'<div class="chip-wrap">{shown}</div>', unsafe_allow_html=True)


st.set_page_config(
    page_title="Unduh Laporan TL506",
    page_icon="📥",
    layout="wide",
)
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

st.markdown(
    """
    <div class="app-hero">
        <div class="tag">AML DATA REPORTING</div>
        <h1>Unduh Laporan TL506</h1>
        <p>Unduh laporan TL506 dari banyak branch sekaligus.
        Hasil dikemas dalam satu file ZIP berisi folder TL506 sesuai tanggal laporan.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

col_form, col_side = st.columns([3, 2], gap="large")

# ----------------------------- Kolom kiri: input -----------------------------
with col_form:
    with st.container(border=True):
        st.markdown('<div class="section-title">Parameter Laporan</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="section-sub">Pilih tanggal dan masukkan kode branch.</div>',
            unsafe_allow_html=True,
        )

        selected_date = st.date_input(
            "Tanggal laporan",
            value=date.today(),
            format="DD/MM/YYYY",
        )
        branch_input = st.text_area(
            "Kode branch",
            placeholder="Contoh:\n0390\n1079\n0261",
            help="Isi satu kode branch per baris (angka 1-5 digit). "
                 "Tekan Ctrl+Enter agar daftar diperbarui.",
            height=200,
        )

        # Pratinjau kode branch secara langsung
        preview_codes = None
        if branch_input.strip():
            try:
                preview_codes = parse_branch_codes(branch_input)
            except ValueError as error:
                st.warning(str(error), icon="⚠️")
            else:
                st.caption(f"{len(preview_codes)} branch siap diproses:")
                render_chips(preview_codes)

        st.write("")
        submitted = st.button(
            "Mulai unduh",
            type="primary",
            use_container_width=True,
            icon="📥",
        )

# ----------------------------- Kolom kanan: panduan -----------------------------
with col_side:
    with st.container(border=True):
        st.markdown('<div class="section-title">Cara Penggunaan</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="section-sub">Ikuti langkah berikut.</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class="step"><div class="num">1</div>
                <div class="txt"><b>Pilih tanggal laporan</b>
                <span>Tanggal data TL506 yang ingin diunduh.</span></div></div>
            <div class="step"><div class="num">2</div>
                <div class="txt"><b>Masukkan kode branch</b>
                <span>Satu kode per baris. Kode kurang dari 5 digit otomatis diberi nol di depan.</span></div></div>
            <div class="step"><div class="num">3</div>
                <div class="txt"><b>Klik Mulai unduh</b>
                <span>Pantau progres sampai selesai.</span></div></div>
            <div class="step"><div class="num">4</div>
                <div class="txt"><b>Unduh file ZIP</b>
                <span>Tombol unduh muncul setelah proses selesai.</span></div></div>
            """,
            unsafe_allow_html=True,
        )

    with st.container(border=True):
        st.markdown('<div class="section-title">Catatan</div>', unsafe_allow_html=True)
        st.caption(
            "• Pastikan akses BRISIM sudah aktif sebelum memulai.\n\n"
            "• Kode branch tidak boleh duplikat, termasuk yang sama setelah "
            "ditambah nol di depan (mis. 390 dan 0390).\n\n"
            "• Jangan menutup halaman selama proses berjalan."
        )

# ----------------------------- Proses unduh -----------------------------
if submitted:
    st.session_state.pop("tl506_zip_data", None)
    st.session_state.pop("tl506_zip_name", None)
    st.session_state.pop("tl506_summary", None)

    try:
        branch_codes = parse_branch_codes(branch_input)
    except ValueError as error:
        st.error(str(error), icon="🚫")
    else:
        date_iso = selected_date.isoformat()
        folder_name = f"TL506_{selected_date.strftime('%d_%m_%Y')}"

        st.write("")
        with st.container(border=True):
            st.markdown('<div class="section-title">Progres Unduhan</div>', unsafe_allow_html=True)
            progress = st.progress(0, text="Menyiapkan unduhan...")
            status = st.empty()
            log = st.empty()

            def update_status(message):
                status.info(message)

            def update_progress(current, total, branch_code, message):
                progress.progress(
                    current / total,
                    text=f"{message} ({current}/{total})",
                )
                log.caption(f"Branch {branch_code}: {message}")

            def update_log(message):
                log.caption(message)

            try:
                with tempfile.TemporaryDirectory(prefix="tl506_") as temp_dir:
                    output_dir = Path(temp_dir) / folder_name
                    worker_error = run_download_worker(
                        date_iso,
                        branch_codes,
                        output_dir,
                        update_status,
                        update_progress,
                        update_log,
                    )

                    if worker_error:
                        status.empty()
                        error_type = worker_error.get(
                            "error_type",
                            "WorkerError",
                        )
                        error_message = worker_error.get("message") or (
                            "Tidak ada pesan error dari proses."
                        )
                        st.error(
                            f"Proses unduh gagal ({error_type}): {error_message}",
                            icon="🚫",
                        )
                        if worker_error.get("traceback"):
                            with st.expander("Detail teknis"):
                                st.code(
                                    worker_error["traceback"],
                                    language="text",
                                )
                    else:
                        excel_files = sorted(output_dir.glob("*.xlsx"))
                        if not excel_files:
                            status.empty()
                            st.warning(
                                "Tidak ada file yang berhasil diunduh. "
                                "Periksa kembali kode branch dan akses BRISIM.",
                                icon="⚠️",
                            )
                        else:
                            zip_path = Path(temp_dir) / f"{folder_name}.zip"
                            with zipfile.ZipFile(
                                zip_path,
                                mode="w",
                                compression=zipfile.ZIP_DEFLATED,
                            ) as archive:
                                for file_path in excel_files:
                                    archive.write(
                                        file_path,
                                        arcname=(
                                            f"{folder_name}/{file_path.name}"
                                        ),
                                    )

                            st.session_state["tl506_zip_data"] = (
                                zip_path.read_bytes()
                            )
                            st.session_state["tl506_zip_name"] = zip_path.name
                            st.session_state["tl506_summary"] = {
                                "tanggal": format_tanggal(selected_date),
                                "folder": folder_name,
                                "diminta": len(branch_codes),
                                "berhasil": len(excel_files),
                                "ukuran_zip": zip_path.stat().st_size,
                                "files": [
                                    (f.name, f.stat().st_size)
                                    for f in excel_files
                                ],
                            }
                            status.empty()
                            log.empty()
                            progress.progress(1.0, text="Semua unduhan selesai.")
                            st.success(
                                f"Selesai. {len(excel_files)} file Excel tersedia "
                                f"dalam folder {folder_name}.",
                                icon="✅",
                            )
            except Exception as error:
                status.empty()
                message = str(error).strip() or "Tidak ada pesan error dari proses."
                st.error(
                    f"Proses unduh gagal ({type(error).__name__}): {message}",
                    icon="🚫",
                )
                with st.expander("Detail teknis"):
                    st.exception(error)

# ----------------------------- Hasil -----------------------------
if st.session_state.get("tl506_zip_data"):
    summary = st.session_state.get("tl506_summary", {})

    st.write("")
    with st.container(border=True):
        st.markdown('<div class="section-title">Hasil Unduhan</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="section-sub">Laporan tanggal {summary.get("tanggal", "-")}</div>',
            unsafe_allow_html=True,
        )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Branch diminta", summary.get("diminta", "-"))
        m2.metric("File berhasil", summary.get("berhasil", "-"))
        m3.metric("Folder", summary.get("folder", "-"))
        m4.metric("Ukuran ZIP", format_size(summary.get("ukuran_zip", 0)))

        if summary.get("diminta") and summary.get("berhasil") is not None:
            if summary["berhasil"] < summary["diminta"]:
                st.warning(
                    f"Hanya {summary['berhasil']} dari {summary['diminta']} branch "
                    "yang menghasilkan file. Periksa kode branch yang tidak terunduh.",
                    icon="⚠️",
                )

        if summary.get("files"):
            with st.expander(f"Lihat daftar file ({len(summary['files'])})"):
                st.dataframe(
                    [
                        {"Nama file": name, "Ukuran": format_size(size)}
                        for name, size in summary["files"]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

        st.download_button(
            "Unduh folder TL506 (ZIP)",
            data=st.session_state["tl506_zip_data"],
            file_name=st.session_state["tl506_zip_name"],
            mime="application/zip",
            type="primary",
            use_container_width=True,
            icon="⬇️",
        )

st.markdown(
    '<div class="footer-note">Alat internal pengunduhan laporan TL506</div>',
    unsafe_allow_html=True,
)