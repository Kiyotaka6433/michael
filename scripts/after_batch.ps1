# Overnight batch, second pass (18 Oct): build_library.py merges its state saves, so other work can run in parallel.
#   1. rewrite and compare EVERY topic note with the recall fixes on (title-context retry, compound splitting);
#      a rewrite replaces the current note only if better() - the old one moves to <Subject>/Archive/
#   2. the remaining key-points notes
# Output goes through cmd so library\build.log stays UTF-8 (PowerShell 5.1 redirection writes UTF-16).
$root = "C:\Users\aryan\OneDrive\Desktop\michael"
Set-Location $root
$py = "$root\.venv\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"
cmd /c "`"$py`" -u scripts/build_library.py retopics --all-topics >> library\build.log 2>&1"
cmd /c "`"$py`" -u scripts/build_library.py keypoints >> library\build.log 2>&1"
