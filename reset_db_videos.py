import sqlite3

db = '/opt/library_scanner/data/db/library_scanner.db'
conn = sqlite3.connect(db)

# Salva le directory configurate (le vogliamo mantenere)
dirs = conn.execute("SELECT * FROM scan_directories").fetchall()
print(f"Directory configurate: {len(dirs)}")
for d in dirs:
    print(" ", d)

# Reset solo video_files e ocr_logs
conn.execute("DELETE FROM ocr_logs")
conn.execute("DELETE FROM video_files")
conn.commit()

# Verifica
n_videos = conn.execute("SELECT COUNT(*) FROM video_files").fetchone()[0]
n_logs   = conn.execute("SELECT COUNT(*) FROM ocr_logs").fetchone()[0]
n_dirs   = conn.execute("SELECT COUNT(*) FROM scan_directories").fetchone()[0]
print(f"video_files: {n_videos} | ocr_logs: {n_logs} | scan_directories: {n_dirs}")
conn.close()
print("Done.")
