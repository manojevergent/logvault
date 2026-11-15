import csv
import io
import zipfile

p = "/data/exports/LIGHTBOX/job_976.csv.zip"
with zipfile.ZipFile(p) as z:
    names = z.namelist()
    data = z.read(names[0]).decode("utf-8", "replace").splitlines()

print("member:", names[0])
print("lines_total:", len(data))
print("header:", data[0][:90])
rows = list(csv.reader(io.StringIO("\n".join(data[1:]))))
print("data_rows:", len(rows))
ts = [r[0] for r in rows if r]
print("first_ts:", ts[0])
print("last_ts :", ts[-1])
print("min_ts  :", min(ts))
print("max_ts  :", max(ts))
print("window  : 2026-11-15 12:39:52 .. 2026-11-15 14:39:52 UTC")
