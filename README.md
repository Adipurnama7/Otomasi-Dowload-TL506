# Unduh laporan TL506 dengan Streamlit

## Menjalankan aplikasi

Jalankan perintah berikut dari folder aplikasi:

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m streamlit run streamlit_app.py
```

Masukkan tanggal laporan dan kode branch (satu kode per baris), lalu klik
**Mulai unduh**. Jika diminta, login BRISIM dan selesaikan OTP pada jendela
browser yang terbuka. Jika pemberitahuan BRISIM muncul, aplikasi akan mencoba
menekan **Setuju** dan menunggu dialog tertutup. Setelah proses selesai, klik
**Unduh folder TL506**.

Browser mengunduh satu file ZIP bernama `TL506_DD_MM_YYYY.zip`. Setelah
ekstrak, ZIP berisi folder `TL506_DD_MM_YYYY` beserta file Excel per branch.
Format nama file Excel tetap `TL506_YYYY-MM-DD_KODEBRANCH.xlsx`.
