import shutil, glob, os

src = r"C:\Users\Onyema Ifechukwu\.claude\projects\C--WINDOWS-system32\memory"
dst = r"C:\Users\Onyema Ifechukwu\Kardit\.claude\memory"

os.makedirs(dst, exist_ok=True)
files = glob.glob(os.path.join(src, "*.md"))
for f in files:
    shutil.copy2(f, dst)

print(f"{len(files)} files copied to {dst}")
